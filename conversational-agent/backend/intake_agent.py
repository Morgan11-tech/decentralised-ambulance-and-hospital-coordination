"""The intake agent's decision loop.

    caller text -> Gemini (update state, next question)
                -> incomplete?  ask next question
                -> complete?    Jev classification
                                 -> low confidence (once)?  clarification question
                                 -> otherwise               build Incident -> MongoDB

This class knows nothing about audio or WebSockets: it takes caller text and
returns what the agent should say next. `main.py` wires it to voice, and the
tests drive it with fake services.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from config import Settings, get_settings
from models.classification import CLASSIFICATION_FIELDS, ClassificationResult
from models.conversation import GeminiTurn, TranscriptEntry
from models.incident import ClassificationSummary, Incident, IncidentState, Location
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
    "breathing_concern": "Is the patient breathing normally?",
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


def merge_gemini_turn(state: IncidentState, turn: GeminiTurn) -> IncidentState:
    """Merge Gemini's view into the working state.

    New information overrides old values, but null/"unknown" never erases
    something the caller already told us.
    """
    merged = state.model_copy(deep=True)
    if turn.location:
        merged.location = turn.location
    if turn.incident_description:
        merged.incident_description = turn.incident_description
    if turn.conversation_summary:
        merged.conversation_summary = turn.conversation_summary
    if turn.number_of_patients is not None and turn.number_of_patients >= 1:
        merged.number_of_patients = turn.number_of_patients
    for field in ("consciousness", "breathing", "bleeding"):
        value = getattr(turn, field)
        if value != "unknown":
            setattr(merged.patient, field, value)
    return merged


def build_incident(
    state: IncidentState, result: ClassificationResult, threshold: float
) -> Incident:
    """Build the canonical Incident payload from the working state + classification."""
    return Incident(
        session_id=state.session_id,
        location=Location(raw_text=state.location),
        incident_description=state.incident_description or "No description provided by caller.",
        incident_type=result.incident_type.final_value(threshold),
        severity=result.severity.final_value(threshold),
        patient=state.patient.model_copy(),
        number_of_patients=state.number_of_patients,
        classification=ClassificationSummary(
            incident_type_confidence=result.incident_type.confidence,
            severity_confidence=result.severity.confidence,
            consciousness_concern=result.consciousness_concern.final_value(threshold),
            consciousness_concern_confidence=result.consciousness_concern.confidence,
            breathing_concern=result.breathing_concern.final_value(threshold),
            breathing_concern_confidence=result.breathing_concern.confidence,
            classifier=result.model or "unavailable",
        ),
        source="voice_agent",
    )


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
        llm: Callable[[str], Awaitable[GeminiTurn]] = gemini_service.generate_turn,
        classifier=jev_service.classify,
        store=mongodb_service.save_incident,
        settings: Settings | None = None,
    ):
        self.emit = emit
        self.llm = llm
        self.classifier = classifier
        self.store = store
        self.settings = settings or get_settings()

        self.state = IncidentState(session_id=session_id)
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
        if not self.state.incident_description:
            return False
        result = await self._classify()
        await self._finalize(result)
        return True

    # --- decision loop ------------------------------------------------------------

    async def _process(self) -> AgentReply:
        turn = await self._call_llm(
            build_turn_prompt(self._state_dict(), self._transcript_dicts(), self.questions_asked)
        )
        self.state = merge_gemini_turn(self.state, turn)
        await self.emit({"type": "incident_state", "state": self.state.model_dump()})

        if self.state.status == "clarifying":
            # The caller just answered our one clarification question.
            return await self._classify_and_finish(allow_clarification=False)

        if turn.ready_for_classification or self.questions_asked >= MAX_INTAKE_QUESTIONS:
            return await self._classify_and_finish(allow_clarification=True)

        await self._say(turn.reply)
        self.questions_asked += 1
        return AgentReply(turn.reply)

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
        await self._finalize(result)
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
        event = classification_event(result, self.threshold, run=len(self.classification_runs) + 1)
        self.classification_runs.append(event)
        await self.emit({"type": "classification", "data": event})
        if result.error:
            await self.emit(
                {"type": "error", "source": "jev", "message": result.error, "recoverable": True}
            )
        return result

    async def _clarification_question(self, uncertain: list[str]) -> str:
        prompt = build_clarification_prompt(
            self._state_dict(), self._transcript_dicts(), uncertain
        )
        try:
            turn = await self.llm(prompt)
            if turn.reply.strip():
                return turn.reply
        except Exception:
            pass
        return FALLBACK_CLARIFICATIONS[uncertain[0]]

    async def _finalize(self, result: ClassificationResult) -> None:
        incident = build_incident(self.state, result, self.threshold)
        self.incident = incident
        self.state.incident_type = incident.incident_type
        self.state.severity = incident.severity
        self.state.status = "completed"

        try:
            await self.store(incident, self._metadata())
            self.persisted, self.persistence_error = True, None
        except Exception as exc:  # keep the incident in memory and report
            self.persisted, self.persistence_error = False, f"{type(exc).__name__}: {exc}"

        await self.emit({"type": "incident_state", "state": self.state.model_dump()})
        await self.emit(
            {
                "type": "incident_complete",
                "incident": incident.model_dump(mode="json"),
                "persisted": self.persisted,
                "persistence_error": self.persistence_error,
            }
        )

    # --- helpers ------------------------------------------------------------------

    async def _call_llm(self, prompt: str) -> GeminiTurn:
        try:
            return await self.llm(prompt)
        except Exception as exc:
            raise AgentError("gemini", f"{type(exc).__name__}: {exc}") from exc

    async def _say(self, text: str) -> None:
        self.transcript.append(TranscriptEntry(speaker="agent", text=text))

    def _state_dict(self) -> dict:
        return self.state.model_dump(exclude={"session_id", "status"})

    def _transcript_dicts(self) -> list[dict]:
        return [t.model_dump(include={"speaker", "text"}) for t in self.transcript]

    def _metadata(self) -> dict:
        return {
            "session_id": self.state.session_id,
            "transcript": [t.model_dump(mode="json") for t in self.transcript],
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
