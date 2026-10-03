"""Adaptive question selection, state merging and JSON construction (no LLM involved).

Scenario tests A–E feed the extraction Gemini would make from the caller's words
and check which information the backend asks for next.
"""

from intake_policy import (
    apply_classification,
    build_incident,
    incident_payload,
    merge_turn,
    missing_information,
    next_topic,
    ready_for_classification,
    topic_overview,
)
from models.incident import Incident
from models.working_state import WorkingState
from tests.fakes import classification, turn

VITALS_AND_CORE = {"location", "what_happened", "consciousness", "breathing"}


def after(*turns) -> WorkingState:
    state = WorkingState(session_id="s-1")
    for i, t in enumerate(turns, start=1):
        state = merge_turn(state, t, i)
    return state


# --- scenarios A–E ------------------------------------------------------------------


def test_a_everything_given_up_front_only_bleeding_is_left():
    # "I'm at Vrijhof. My friend fell from his bike. He's conscious and breathing normally."
    state = after(turn(
        location="Vrijhof", incident_description="Friend fell from his bike.", mechanism="bicycle fall",
        patient_count=1, consciousness="conscious", breathing="normal", severe_bleeding="unknown",
    ))
    assert not VITALS_AND_CORE & set(missing_information(state))
    assert next_topic(state) == "severe_bleeding"


def test_a_without_injury_bleeding_question_is_skipped():
    state = after(turn(
        location="Vrijhof", incident_description="Friend fell from his bike.", patient_count=1,
        consciousness="conscious", breathing="normal", severe_bleeding="absent",
    ))
    assert next_topic(state) is None
    assert ready_for_classification(state)


def test_b_collapse_asks_location_first():
    # "My father collapsed."
    state = after(turn(incident_description="Father suddenly collapsed.", patient_count=1, severe_bleeding="not_relevant"))
    assert missing_information(state) == ["location", "consciousness", "breathing"]
    assert next_topic(state) == "location"


def test_c_car_crash_does_not_ask_count_or_entrapment():
    # "There's been a car crash at Hengelosestraat. Three people are injured and one is trapped."
    state = after(turn(
        location="Hengelosestraat", incident_description="Car crash with three injured, one trapped.",
        mechanism="car collision", patient_count=3, entrapment="yes", immediate_danger="unknown",
    ))
    missing = missing_information(state)
    assert "patient_count" not in missing and "entrapment" not in missing
    assert next_topic(state) == "consciousness"  # vital information first
    assert state.scene.entrapment.value == "yes"


def test_d_neurological_symptoms_are_observations_not_diagnoses():
    # "My husband can't move his left arm and his speech sounds strange. We're at home at Calslaan 12."
    state = after(turn(
        location="Home, Calslaan 12", incident_description="Husband cannot move his left arm and his speech sounds strange.",
        patient_count=1, consciousness="conscious", severe_bleeding="not_relevant",
        symptoms=["left arm weakness", "speech difficulty"],
    ))
    assert state.patient_state.symptoms == ["left arm weakness", "speech difficulty"]
    assert next_topic(state) == "breathing"
    payload = incident_payload(state)
    assert "diagnosis" not in str(payload) and "stroke" not in str(payload).lower()


def test_e_weird_breathing_noises_never_become_normal():
    # "He's making weird breathing noises."
    state = after(turn(incident_description="Man collapsed.", breathing="normal"), turn(breathing="abnormal"))
    assert state.patient_state.breathing.value == "abnormal"  # correction is applied
    state = after(turn(breathing="abnormal"), turn(breathing="unknown"))
    assert state.patient_state.breathing.value == "abnormal"  # unknown never erases


# --- merge rules ------------------------------------------------------------------------


def test_merge_tracks_status_and_source_turn():
    state = after(turn(incident_description="Father collapsed."), turn(location="University of Twente"))
    assert state.incident.description.source_turn == 1
    assert state.location.model_dump() == {"value": "University of Twente", "status": "known", "source_turn": 2}
    assert state.patient_state.consciousness.status == "unknown"


def test_merge_keeps_known_values_and_symptoms():
    state = after(
        turn(location="Enschede", consciousness="conscious", symptoms=["chest pain", "bleeding"]),
        turn(location=None, consciousness="unknown", symptoms=["chest pain", "minor bleeding", "Chest pain"], patient_count=0),
        turn(symptoms=[]),
    )
    assert state.location.value == "Enschede"
    assert state.patient_state.consciousness.value == "conscious"
    assert state.patient_state.symptoms == ["chest pain", "minor bleeding"]  # refined, deduplicated, not erased
    assert state.patients.count.status == "unknown"  # 0 patients is ignored


def test_relevance_can_switch_on_later():
    state = after(turn(), turn(entrapment="unknown"))
    assert state.scene.entrapment.status == "unknown"
    assert "entrapment" in missing_information(state)


def test_each_topic_is_asked_at_most_once():
    state = after(turn(incident_description="Someone is lying on the ground.", patient_count=1, severe_bleeding="not_relevant"))
    state.asked_topics += ["location", "consciousness"]
    assert missing_information(state) == ["breathing"]
    overview = {t["topic"]: t["status"] for t in topic_overview(state, "breathing")}
    assert overview["location"] == "unanswered" and overview["breathing"] == "next"
    assert overview["what_happened"] == "known" and overview["entrapment"] == "not_relevant"


# --- JSON construction ------------------------------------------------------------------


def test_draft_json_fills_up_turn_by_turn():
    state = WorkingState(session_id="s-1")
    draft = incident_payload(state)
    assert draft["incident"]["description"] is None and draft["location"]["raw_text"] is None
    assert draft["status"] == "collecting" and draft["incident"]["type"] == "unknown"

    state = merge_turn(state, turn(incident_description="Father suddenly collapsed.", patient_count=1), 1)
    assert incident_payload(state)["incident"]["description"] == "Father suddenly collapsed."

    state = merge_turn(state, turn(location="University of Twente"), 2)
    state = merge_turn(state, turn(consciousness="unconscious"), 3)
    draft = incident_payload(state)
    assert draft["location"]["raw_text"] == "University of Twente"
    assert draft["patients"]["primary_patient"]["consciousness"] == "unconscious"
    assert draft["patients"]["primary_patient"]["breathing"] == "unknown"
    assert draft["incident_id"] == state.incident_id  # same id as the final incident


def test_jev_enriches_the_same_state_and_json():
    state = after(turn(location="Vrijhof", incident_description="Friend fell off his bike.", consciousness="conscious"))
    apply_classification(state, classification(0.9, breathing_conf=0.5), threshold=0.7)
    assert state.incident_type == "trauma" and state.severity == "urgent"
    draft = incident_payload(state)
    assert draft["incident"]["type"] == "trauma"
    assert draft["classification"]["incident_type"] == {"value": "trauma", "confidence": 0.9}
    assert draft["classification"]["breathing_concern"] == {"value": "uncertain", "confidence": 0.5}


def test_final_incident_is_canonical_and_clean():
    state = after(turn(
        location="Outside the Vrijhof, University of Twente", incident_description="Friend fell off his bicycle and hit his head.",
        mechanism="bicycle fall", patient_count=1, consciousness="conscious", breathing="normal",
        severe_bleeding="absent", symptoms=["head injury"],
    ))
    state.asked_topics.append("severe_bleeding")
    apply_classification(state, classification(0.9), threshold=0.7)
    incident = build_incident(state)

    assert isinstance(incident, Incident)
    payload = incident.model_dump(mode="json")
    assert payload["incident_id"] == state.incident_id
    assert payload["incident"] == {
        "description": "Friend fell off his bicycle and hit his head.", "mechanism": "bicycle fall",
        "type": "trauma", "severity": "urgent",
    }
    assert payload["patients"] == {
        "count": 1,
        "primary_patient": {"consciousness": "conscious", "breathing": "normal", "severe_bleeding": "absent", "symptoms": ["head injury"]},
    }
    assert payload["scene"] == {"entrapment": "not_relevant", "immediate_danger": "not_relevant"}
    assert payload["status"] == "ready_for_dispatch"
    # no LLM bookkeeping leaks into the contract
    assert "source_turn" not in str(payload) and "asked_topics" not in str(payload)


def test_final_incident_when_jev_was_unavailable_and_nothing_known():
    from models.classification import ClassificationResult

    state = WorkingState(session_id="s")
    apply_classification(state, ClassificationResult.unavailable("down"), threshold=0.7)
    incident = build_incident(state)
    assert incident.incident.type == "uncertain" and incident.incident.severity == "uncertain"
    assert incident.incident.description  # never empty
    assert incident.classification.severity.confidence is None
    assert incident.patients.primary_patient.severe_bleeding == "unknown"
