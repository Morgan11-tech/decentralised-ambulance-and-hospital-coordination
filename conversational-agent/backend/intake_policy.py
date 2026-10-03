"""What information do we still need? (deterministic, no LLM)

Dutch-112-inspired intake pattern:
    where → what happened → vital functions (responsiveness, breathing,
    severe bleeding) → incident-specific context, only when relevant.

Gemini extracts facts and phrases questions; this module decides WHICH piece of
information to ask for next and WHEN to stop. Every topic is asked at most once,
and topics Gemini marks `not_relevant` are skipped.
"""

from datetime import datetime, timezone

from models.classification import CLASSIFICATION_FIELDS, ClassificationResult
from models.conversation import GeminiTurn
from models.incident import Incident
from models.working_state import Fact, LabelView, Topic, WorkingState

# Highest priority first.
TOPIC_PRIORITY: tuple[Topic, ...] = (
    "location",
    "what_happened",
    "consciousness",
    "breathing",
    "severe_bleeding",
    "patient_count",
    "entrapment",
    "immediate_danger",
)

# Used when Gemini did not phrase a question for the chosen topic.
FALLBACK_QUESTIONS: dict[Topic, str] = {
    "location": "Where is the emergency?",
    "what_happened": "Tell me what happened.",
    "consciousness": "Are they responding to you?",
    "breathing": "Are they breathing normally?",
    "severe_bleeding": "Is there any severe bleeding?",
    "patient_count": "About how many people are injured?",
    "entrapment": "Is anyone trapped?",
    "immediate_danger": "Is there any immediate danger at the scene?",
}

UNKNOWN_DESCRIPTION = "No description provided by caller."


# --- merging Gemini's extraction ---------------------------------------------------


def _update(fact: Fact, value: str | int | None, status: str, turn: int) -> None:
    """Known values are only replaced by other known values (corrections);
    "unknown" / "not_relevant" never erase something the caller already said."""
    if status == "known":
        if fact.status != "known" or fact.value != value:
            fact.value, fact.status, fact.source_turn = value, "known", turn
    elif fact.status != "known" and fact.status != status:
        fact.value, fact.status, fact.source_turn = None, status, turn


def _text(value: str | None) -> tuple[str | None, str]:
    value = (value or "").strip() or None
    return value, "known" if value else "unknown"


def _flag(value: str) -> tuple[str | None, str]:
    """Map an enum answer to (value, status)."""
    if value in ("unknown", "not_relevant"):
        return None, value
    return value, "known"


def merge_turn(state: WorkingState, turn: GeminiTurn, turn_no: int) -> WorkingState:
    merged = state.model_copy(deep=True)
    _update(merged.location, *_text(turn.location), turn_no)
    _update(merged.incident.description, *_text(turn.incident_description), turn_no)
    _update(merged.incident.mechanism, *_text(turn.mechanism), turn_no)

    count = turn.patient_count if turn.patient_count and turn.patient_count >= 1 else None
    _update(merged.patients.count, count, "known" if count else "unknown", turn_no)

    ps = merged.patient_state
    _update(ps.consciousness, *_flag(turn.consciousness), turn_no)
    _update(ps.breathing, *_flag(turn.breathing), turn_no)
    _update(ps.severe_bleeding, *_flag(turn.severe_bleeding), turn_no)
    _update(merged.scene.entrapment, *_flag(turn.entrapment), turn_no)
    _update(merged.scene.immediate_danger, *_flag(turn.immediate_danger), turn_no)

    # Gemini returns the complete, refined list (it sees the previous one); an empty
    # list never erases symptoms we already have.
    symptoms: list[str] = []
    for symptom in (s.strip() for s in turn.symptoms):
        if symptom and symptom.lower() not in {s.lower() for s in symptoms}:
            symptoms.append(symptom)
    if symptoms:
        ps.symptoms = symptoms

    if turn.conversation_summary.strip():
        merged.conversation_summary = turn.conversation_summary.strip()
    return merged


# --- what is missing? ----------------------------------------------------------------


def missing_information(state: WorkingState) -> list[Topic]:
    """Relevant, still-unknown topics that have not been asked yet, highest priority first."""
    facts = state.facts()
    return [
        topic
        for topic in TOPIC_PRIORITY
        if facts[topic].status == "unknown" and topic not in state.asked_topics
    ]


def next_topic(state: WorkingState) -> Topic | None:
    missing = missing_information(state)
    return missing[0] if missing else None


def ready_for_classification(state: WorkingState) -> bool:
    """Stop asking once nothing relevant is missing (unknown answers are acceptable)."""
    return not missing_information(state)


def topic_overview(state: WorkingState, asking: Topic | None) -> list[dict]:
    """Debug-panel view: every topic with known / next / missing / unanswered / not_relevant."""
    facts, missing = state.facts(), missing_information(state)
    overview = []
    for topic in TOPIC_PRIORITY:
        fact = facts[topic]
        if fact.status == "known":
            status = "known"
        elif fact.status == "not_relevant":
            status = "not_relevant"
        elif topic == asking:
            status = "next"
        elif topic in missing:
            status = "missing"
        else:
            status = "unanswered"  # asked, but the caller could not tell
        overview.append({"topic": topic, "status": status, "value": fact.value})
    return overview


# --- Jev enrichment ------------------------------------------------------------------


def apply_classification(state: WorkingState, result: ClassificationResult, threshold: float) -> None:
    """Write Jev's (thresholded) labels into the same working state."""
    state.classification = {
        name: LabelView(value=getattr(result, name).final_value(threshold), confidence=getattr(result, name).confidence)
        for name in CLASSIFICATION_FIELDS
    }
    state.incident_type = state.classification["incident_type"].value
    state.severity = state.classification["severity"].value


# --- canonical payload -------------------------------------------------------------------


def _value(fact: Fact, not_relevant: str = "unknown"):
    if fact.status == "known":
        return fact.value
    return not_relevant if fact.status == "not_relevant" else "unknown"


def incident_payload(state: WorkingState, final: bool = False) -> dict:
    """The canonical Incident JSON built from the working state.

    Used live (draft: may contain "unknown" labels and status "collecting") and at the
    end (final: validated against the `Incident` model). Same structure either way.
    """
    labels = state.classification or {}

    def label(name: str) -> dict:
        view = labels.get(name)
        return {"value": view.value, "confidence": view.confidence} if view else {"value": "unknown", "confidence": None}

    description = state.incident.description.value
    return {
        "schema_version": "1.0",
        "incident_id": state.incident_id,
        "session_id": state.session_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z") if final else None,
        "source": "voice_agent",
        "location": {"raw_text": state.location.value, "latitude": None, "longitude": None},
        "incident": {
            "description": description or (UNKNOWN_DESCRIPTION if final else None),
            "mechanism": state.incident.mechanism.value,
            "type": state.incident_type,
            "severity": state.severity,
        },
        "patients": {
            "count": state.patients.count.value,
            "primary_patient": {
                "consciousness": _value(state.patient_state.consciousness),
                "breathing": _value(state.patient_state.breathing),
                "severe_bleeding": _value(state.patient_state.severe_bleeding),
                "symptoms": list(state.patient_state.symptoms),
            },
        },
        "scene": {
            "entrapment": _value(state.scene.entrapment, "not_relevant"),
            "immediate_danger": _value(state.scene.immediate_danger, "not_relevant"),
        },
        "classification": {name: label(name) for name in CLASSIFICATION_FIELDS},
        "status": "ready_for_dispatch" if final else "collecting",
    }


def build_incident(state: WorkingState) -> Incident:
    """The final, validated canonical Incident (requires Jev labels in the state)."""
    return Incident.model_validate(incident_payload(state, final=True))
