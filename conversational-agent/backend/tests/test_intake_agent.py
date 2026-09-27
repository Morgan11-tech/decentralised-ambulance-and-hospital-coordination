"""Tests for the intake decision loop, using fake Gemini / Jev / MongoDB."""

import pytest

from config import Settings
from intake_agent import (
    MAX_INTAKE_QUESTIONS,
    AgentError,
    IntakeAgent,
    build_incident,
    merge_gemini_turn,
)
from models.classification import ClassificationResult, LabelResult
from models.conversation import GeminiTurn
from models.incident import Incident, IncidentState, PatientState
from prompts.emergency_agent import CLOSING_MESSAGE, GREETING

SETTINGS = Settings(_env_file=None, jev_confidence_threshold=0.7, max_classification_clarifications=1)


def turn(reply="Is he conscious?", ready=False, **fields) -> GeminiTurn:
    defaults = dict(
        location=None,
        incident_description=None,
        number_of_patients=None,
        consciousness="unknown",
        breathing="unknown",
        bleeding="unknown",
        conversation_summary="",
    )
    defaults.update(fields)
    return GeminiTurn(reply=reply, ready_for_classification=ready, **defaults)


def classification(conf: float = 0.9, breathing_conf: float | None = None, model="jev-1.13.0"):
    return ClassificationResult(
        incident_type=LabelResult(value="trauma", confidence=conf),
        severity=LabelResult(value="urgent", confidence=conf),
        consciousness_concern=LabelResult(value="no", confidence=conf),
        breathing_concern=LabelResult(
            value="no", confidence=conf if breathing_conf is None else breathing_conf
        ),
        model=model,
    )


class Fakes:
    """Scripted Gemini and Jev responses plus a recording MongoDB store."""

    def __init__(self, turns, results, store_error: Exception | None = None):
        self.turns = list(turns)
        self.results = list(results)
        self.store_error = store_error
        self.prompts: list[str] = []
        self.stored: list[tuple[Incident, dict]] = []
        self.events: list[dict] = []
        self.jev_calls = 0

    async def llm(self, prompt):
        self.prompts.append(prompt)
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def classifier(self, state, transcript):
        self.jev_calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"model": item.model, "answers": {}}

    async def store(self, incident, metadata):
        if self.store_error:
            raise self.store_error
        self.stored.append((incident, metadata))

    async def emit(self, event):
        self.events.append(event)

    def agent(self) -> IntakeAgent:
        return IntakeAgent(
            "session-1", self.emit, llm=self.llm, classifier=self.classifier,
            store=self.store, settings=SETTINGS,
        )

    def events_of(self, kind):
        return [e for e in self.events if e["type"] == kind]


COMPLETE = dict(
    location="University of Twente",
    incident_description="Cyclist fell off his bicycle and hit his head.",
    number_of_patients=1,
    consciousness="conscious",
    breathing="normal",
    bleeding="present",
    conversation_summary="Friend fell off bicycle, hit head, conscious, bleeding.",
)


# --- pure functions ---------------------------------------------------------------


def test_merge_keeps_known_values_and_adds_new_ones():
    state = IncidentState(
        session_id="s", location="Enschede", patient=PatientState(consciousness="conscious")
    )
    merged = merge_gemini_turn(state, turn(breathing="abnormal", number_of_patients=0))
    assert merged.location == "Enschede"  # null does not erase
    assert merged.patient.consciousness == "conscious"  # unknown does not erase
    assert merged.patient.breathing == "abnormal"  # new info is added
    assert merged.number_of_patients is None  # 0 patients is ignored
    assert state.patient.breathing == "unknown"  # original is not mutated


def test_merge_allows_corrections():
    state = IncidentState(session_id="s", patient=PatientState(breathing="normal"))
    merged = merge_gemini_turn(state, turn(breathing="not_breathing"))
    assert merged.patient.breathing == "not_breathing"


def test_build_incident_applies_threshold():
    state = merge_gemini_turn(IncidentState(session_id="s-1"), turn(**COMPLETE))
    result = classification(conf=0.9, breathing_conf=0.5)
    incident = build_incident(state, result, threshold=0.7)

    payload = incident.model_dump(mode="json")
    assert payload["session_id"] == "s-1"
    assert payload["location"] == {"raw_text": "University of Twente", "latitude": None, "longitude": None}
    assert payload["incident_type"] == "trauma"
    assert payload["severity"] == "urgent"
    assert payload["patient"] == {"consciousness": "conscious", "breathing": "normal", "bleeding": "present"}
    assert payload["classification"]["breathing_concern"] == "uncertain"  # 0.5 < 0.7
    assert payload["classification"]["breathing_concern_confidence"] == 0.5
    assert payload["classification"]["classifier"] == "jev-1.13.0"
    assert payload["source"] == "voice_agent"
    assert payload["status"] == "ready_for_dispatch"


def test_build_incident_when_jev_unavailable():
    state = IncidentState(session_id="s")
    incident = build_incident(state, ClassificationResult.unavailable("down"), threshold=0.7)
    assert incident.incident_type == "uncertain"
    assert incident.severity == "uncertain"
    assert incident.classification.classifier == "unavailable"
    assert incident.incident_description  # never empty


# --- conversation flows --------------------------------------------------------------


async def test_happy_path():
    fakes = Fakes(
        turns=[turn("What is your location?", incident_description="Cyclist fell."), turn("Thank you.", ready=True, **COMPLETE)],
        results=[classification(0.9)],
    )
    agent = fakes.agent()

    assert (await agent.start()).text == GREETING
    reply = await agent.handle_caller_text("My friend fell from his bicycle.")
    assert reply.text == "What is your location?" and not reply.done

    reply = await agent.handle_caller_text("University of Twente, he's awake, breathing, bleeding a bit.")
    assert reply.text == CLOSING_MESSAGE and reply.done
    assert agent.done and agent.persisted

    incident, metadata = fakes.stored[0]
    assert incident.incident_type == "trauma"
    assert [t["speaker"] for t in metadata["transcript"]] == ["agent", "user", "agent", "user", "agent"]
    assert metadata["jev_raw"] == [{"model": "jev-1.13.0", "answers": {}}]
    complete = fakes.events_of("incident_complete")[0]
    assert complete["persisted"] is True
    assert complete["incident"]["incident_id"] == incident.incident_id


async def test_low_confidence_asks_one_clarification_then_stores_uncertain():
    fakes = Fakes(
        turns=[
            turn("Thank you.", ready=True, **COMPLETE),
            turn("Is he breathing normally, or is he struggling to breathe?"),  # clarification
            turn("Thank you.", ready=True, **COMPLETE),  # extraction of the answer
        ],
        results=[classification(0.9, breathing_conf=0.4), classification(0.9, breathing_conf=0.5)],
    )
    agent = fakes.agent()
    await agent.start()

    reply = await agent.handle_caller_text("He's making some strange noises.")
    assert reply.text.startswith("Is he breathing normally") and not reply.done
    assert agent.state.status == "clarifying"
    assert "whether the patient is breathing normally" in fakes.prompts[1]

    reply = await agent.handle_caller_text("I'm not sure.")
    assert reply.done
    assert fakes.jev_calls == 2  # rerun after the answer, no second clarification
    assert agent.clarifications_used == 1
    assert agent.incident.classification.breathing_concern == "uncertain"
    assert len(fakes.events_of("classification")) == 2


async def test_clarification_resolves_uncertainty():
    fakes = Fakes(
        turns=[turn("Thanks.", ready=True, **COMPLETE), turn("Is he breathing normally?"), turn("Thanks.", ready=True, **COMPLETE)],
        results=[classification(0.9, breathing_conf=0.4), classification(0.9)],
    )
    agent = fakes.agent()
    await agent.start()
    await agent.handle_caller_text("He's making strange noises.")
    await agent.handle_caller_text("Yes, he's breathing normally now.")
    assert agent.incident.classification.breathing_concern == "no"


async def test_clarification_falls_back_if_gemini_fails():
    fakes = Fakes(
        turns=[turn("Thanks.", ready=True, **COMPLETE), RuntimeError("Gemini down")],
        results=[classification(0.9, breathing_conf=0.4)],
    )
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("He's making strange noises.")
    assert reply.text == "Is the patient breathing normally?"


async def test_jev_unavailable_does_not_break_conversation():
    fakes = Fakes(
        turns=[turn("Thanks.", ready=True, **COMPLETE)],
        results=[ClassificationResult.unavailable("Jev HTTP 503")],
    )
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("My friend fell off his bike.")
    assert reply.done  # no pointless clarification during an outage
    assert agent.incident.incident_type == "uncertain"
    assert agent.incident.classification.classifier == "unavailable"
    assert any(e["source"] == "jev" for e in fakes.events_of("error"))
    assert agent.persisted


async def test_jev_exception_does_not_break_conversation():
    fakes = Fakes(turns=[turn("Thanks.", ready=True, **COMPLETE)], results=[TypeError("bad json")])
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("My friend fell off his bike.")
    assert reply.done and agent.incident.severity == "uncertain"


async def test_mongodb_failure_keeps_incident_in_memory():
    fakes = Fakes(
        turns=[turn("Thanks.", ready=True, **COMPLETE)],
        results=[classification(0.9)],
        store_error=ConnectionError("no route to host"),
    )
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("My friend fell off his bike.")
    assert reply.done
    assert agent.incident is not None
    assert agent.persisted is False
    assert "no route to host" in agent.persistence_error
    complete = fakes.events_of("incident_complete")[0]
    assert complete["persisted"] is False and complete["incident"]["incident_type"] == "trauma"


async def test_gemini_failure_can_be_retried():
    fakes = Fakes(turns=[RuntimeError("503"), turn("What is your location?")], results=[])
    agent = fakes.agent()
    await agent.start()
    with pytest.raises(AgentError) as exc_info:
        await agent.handle_caller_text("My dad collapsed.")
    assert exc_info.value.source == "gemini"
    assert agent.awaiting_reply

    reply = await agent.retry()
    assert reply.text == "What is your location?"
    assert not agent.awaiting_reply
    assert [t.text for t in agent.transcript].count("My dad collapsed.") == 1


async def test_question_cap_forces_classification():
    fakes = Fakes(
        turns=[turn("Anything else?", incident_description="Something happened.")] * (MAX_INTAKE_QUESTIONS + 1),
        results=[classification(0.9)],
    )
    agent = fakes.agent()
    await agent.start()
    for _ in range(MAX_INTAKE_QUESTIONS):
        reply = await agent.handle_caller_text("I don't know.")
        assert not reply.done
    reply = await agent.handle_caller_text("I don't know.")
    assert reply.done and fakes.jev_calls == 1


async def test_force_finalize():
    fakes = Fakes(turns=[turn("Where are you?", incident_description="Dad collapsed.")], results=[classification(0.9)])
    agent = fakes.agent()
    await agent.start()
    assert await agent.force_finalize() is False  # nothing known yet

    await agent.handle_caller_text("My dad collapsed.")
    assert await agent.force_finalize() is True
    assert agent.done and len(fakes.stored) == 1
