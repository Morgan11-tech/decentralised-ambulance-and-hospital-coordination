"""The intake agent's decision loop.

    caller text -> Gemini: extract ALL facts + phrase questions for what is still needed
                -> merge into the live working state            (intake_policy.merge_turn)
                -> something relevant missing?  ask ONE question (intake_policy.next_topic)
                -> nothing missing?             Jev classification -> enrich the same state
                                                 -> low confidence (once)?  clarification question
                                                 -> otherwise               canonical Incident -> MongoDB

This class knows nothing about audio or WebSockets: it takes caller text and
returns what the agent should say next. `main.py` wires it to voice, and the
tests drive it with fake services.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from config import Settings, get_settings
from intake_policy import (
    FALLBACK_QUESTIONS,
    apply_classification,
    build_incident,
    incident_payload,
    merge_turn,
    missing_information,
    next_topic,
    topic_overview,
)
from models.classification import CLASSIFICATION_FIELDS, ClassificationResult
from models.conversation import GeminiTurn, TranscriptEntry
from models.incident import Incident
from models.working_state import Topic, WorkingState
from prompts.emergency_agent import (
    CLOSING_MESSAGE,
    GREETING,
    build_clarification_prompt,
    build_turn_prompt,
)
from services import gemini_service, jev_service, mongodb_service

# Hard cap so the conversation can never go on forever.
MAX_INTAKE_QUESTIONS = 8

# Used if Gemini fails while phrasing a clarification question.
FALLBACK_CLARIFICATIONS = {
    "incident_type": "Can you tell me a bit more about what happened to the patient?",
    "severity": "How is the patient doing right now?",
    "consciousness_concern": "Is the patient awake and responding to you?",
    "breathing_concern": "Is the patient breathing normally right now?",
}

Emit = Callable[[dict], Awaitable[None]]


class AgentError(Exception):
    """A failure the user can retry (e.g. Gemini unavailable)."""

    def __init__(self, source: str, message: str):
        super().__init__(message)
        self.source = source


@dataclass
class AgentReply:
    text: str
    done: bool = False


def classification_event(result: ClassificationResult, threshold: float, run: int) -> dict:
    """Debug-panel view of a classification run."""
    return {
        "run": run,
        "model": result.model,
        "error": result.error,
        "threshold": threshold,
        "labels": {
            name: {
                "value": getattr(result, name).value,
                "confidence": getattr(result, name).confidence,
                "final": getattr(result, name).final_value(threshold),
                "probabilities": getattr(result, name).probabilities,
            }
            for name in CLASSIFICATION_FIELDS
        },
        "uncertain_fields": result.uncertain_fields(threshold),
    }


class IntakeAgent:
    def __init__(
        self,
        session_id: str,
        emit: Emit,
        *,
        llm: Callable[[str], Awaitable[GeminiTurn]] = gemini_service.extract_turn,
        clarifier: Callable[[str], Awaitable[str]] = gemini_service.generate_clarification,
        classifier=jev_service.classify,
        store=mongodb_service.save_incident,
        settings: Settings | None = None,
    ):
        self.emit = emit
        self.llm = llm
        self.clarifier = clarifier
        self.classifier = classifier
        self.store = store
        self.settings = settings or get_settings()

        self.state = WorkingState(session_id=session_id)
        self.transcript: list[TranscriptEntry] = []
        self.questions_asked = 0
        self.clarifications_used = 0
        self.classification_runs: list[dict] = []
        self.jev_raw: list[dict] = []
        self.incident: Incident | None = None
        self.persisted = False
        self.persistence_error: str | None = None

    @property
    def threshold(self) -> float:
        return self.settings.jev_confidence_threshold

    @property
    def done(self) -> bool:
        return self.state.status == "completed"

    @property
    def awaiting_reply(self) -> bool:
        """True if the caller spoke and the agent has not answered yet (retryable)."""
        return bool(self.transcript) and self.transcript[-1].speaker == "user" and not self.done

    # --- public API -------------------------------------------------------------

    async def start(self) -> AgentReply:
        await self._say(GREETING)
        await self._emit_state(asking="location")
        return AgentReply(GREETING)

    async def handle_caller_text(self, text: str) -> AgentReply:
        if self.done:
            return AgentReply(CLOSING_MESSAGE, done=True)
        self.transcript.append(TranscriptEntry(speaker="user", text=text))
        return await self._process()

    async def retry(self) -> AgentReply | None:
        """Re-process the last caller message after a failure."""
        return await self._process() if self.awaiting_reply else None

    async def force_finalize(self) -> bool:
        """Caller ended the call: classify what we have (no clarification) and save.
        Returns False if there was nothing useful to save."""
        if self.done:
            return True
        if self.state.incident.description.status != "known":
            return False
        await self._classify()
        await self._finalize()
        return True

    # --- decision loop ------------------------------------------------------------

    async def _process(self) -> AgentReply:
        turn = await self._call_llm(
            build_turn_prompt(
                self.state.model_dump(),
                self._transcript_dicts(),
                missing_information(self.state),
                self.state.asked_topics,
            )
        )
        self.state = merge_turn(self.state, turn, turn_no=self._caller_turns())

        if self.state.status == "clarifying":
            # The caller just answered our one clarification question.
            await self._emit_state(asking=None)
            return await self._classify_and_finish(allow_clarification=False)

        topic = next_topic(self.state)
        if topic is None or self.questions_asked >= MAX_INTAKE_QUESTIONS:
            await self._emit_state(asking=None)
            return await self._classify_and_finish(allow_clarification=True)

        await self._emit_state(asking=topic)
        question = self._question(turn, topic)
        self.state.asked_topics.append(topic)
        await self._say(question)
        self.questions_asked += 1
        return AgentReply(question)

    async def _classify_and_finish(self, allow_clarification: bool) -> AgentReply:
        result = await self._classify()
        uncertain = result.uncertain_fields(self.threshold)
        can_clarify = (
            allow_clarification
            and result.error is None  # asking the caller cannot fix an outage
            and self.clarifications_used < self.settings.max_classification_clarifications
        )
        if uncertain and can_clarify:
            self.clarifications_used += 1
            self.state.status = "clarifying"
            question = await self._clarification_question(uncertain)
            await self._say(question)
            self.questions_asked += 1
            return AgentReply(question)

        await self._say(CLOSING_MESSAGE)
        await self._finalize()
        return AgentReply(CLOSING_MESSAGE, done=True)

    async def _classify(self) -> ClassificationResult:
        previous_status = self.state.status
        self.state.status = "classifying"
        try:
            result, raw = await self.classifier(self.state, self.transcript)
        except Exception as exc:  # Jev problems must never end the conversation
            result, raw = ClassificationResult.unavailable(f"{type(exc).__name__}: {exc}"), None
        self.state.status = previous_status
        if raw is not None:
            self.jev_raw.append(raw)

        apply_classification(self.state, result, self.threshold)  # enrich the same state
        event = classification_event(result, self.threshold, run=len(self.classification_runs) + 1)
        self.classification_runs.append(event)
        await self.emit({"type": "classification", "data": event})
        await self._emit_state(asking=None)
        if result.error:
            await self.emit(
                {"type": "error", "source": "jev", "message": result.error, "recoverable": True}
            )
        return result

    async def _clarification_question(self, uncertain: list[str]) -> str:
        prompt = build_clarification_prompt(
            self.state.model_dump(), self._transcript_dicts(), uncertain
        )
        try:
            question = (await self.clarifier(prompt)).strip()
            if question:
                return question
        except Exception:
            pass
        return FALLBACK_CLARIFICATIONS[uncertain[0]]

    async def _finalize(self) -> None:
        self.incident = build_incident(self.state)
        self.state.status = "completed"

        try:
            await self.store(self.incident, self._metadata())
            self.persisted, self.persistence_error = True, None
        except Exception as exc:  # keep the incident in memory and report
            self.persisted, self.persistence_error = False, f"{type(exc).__name__}: {exc}"

        await self._emit_state(asking=None)
        await self.emit(
            {
                "type": "incident_complete",
                "incident": self.incident.model_dump(mode="json"),
                "persisted": self.persisted,
                "persistence_error": self.persistence_error,
            }
        )

    # --- helpers ------------------------------------------------------------------

    async def _emit_state(self, asking: Topic | None) -> None:
        """Live update for the debug panel: working state, checklist and draft Incident JSON."""
        await self.emit(
            {
                "type": "incident_state",
                "state": self.state.model_dump(mode="json"),
                "topics": topic_overview(self.state, asking),
                "next_topic": asking,
                "incident": self.incident.model_dump(mode="json") if self.incident else incident_payload(self.state),
            }
        )

    @staticmethod
    def _question(turn: GeminiTurn, topic: Topic) -> str:
        question = turn.question_for(topic) or FALLBACK_QUESTIONS[topic]
        preface = (turn.preface or "").strip()
        return f"{preface} {question}" if preface else question

    async def _call_llm(self, prompt: str) -> GeminiTurn:
        try:
            return await self.llm(prompt)
        except Exception as exc:
            raise AgentError("gemini", f"{type(exc).__name__}: {exc}") from exc

    async def _say(self, text: str) -> None:
        self.transcript.append(TranscriptEntry(speaker="agent", text=text))

    def _caller_turns(self) -> int:
        return sum(1 for t in self.transcript if t.speaker == "user")

    def _transcript_dicts(self) -> list[dict]:
        return [t.model_dump(include={"speaker", "text"}) for t in self.transcript]

    def _metadata(self) -> dict:
        return {
            "session_id": self.state.session_id,
            "transcript": [t.model_dump(mode="json") for t in self.transcript],
            "working_state": self.state.model_dump(mode="json"),
            "classification_runs": self.classification_runs,
            "jev_raw": self.jev_raw,
            "clarifications_used": self.clarifications_used,
            "confidence_threshold": self.threshold,
            "models": {
                "llm": self.settings.gemini_llm_model,
                "tts": self.settings.gemini_tts_model,
                "stt": self.settings.deepgram_stt_model,
                "jev": self.settings.jev_model,
            },
        }
