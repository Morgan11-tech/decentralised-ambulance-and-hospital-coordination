from models.classification import CLASSIFICATION_FIELDS
from models.conversation import TranscriptEntry
from models.incident import IncidentState, PatientState
from services.jev_service import QUESTIONS, build_jev_state, build_request, normalize_response

# Shape taken from https://docs.typesafe.ai/api (Choice answers).
RAW_RESPONSE = {
    "model": "jev-1.13.0",
    "answers": {
        "incident_type": {
            "type": "choice",
            "choice": "trauma",
            "probabilities": {"trauma": 0.93, "bleeding": 0.05, "other": 0.02},
            "confidence": 0.91,
        },
        "severity": {
            "type": "choice",
            "choice": "urgent",
            "probabilities": {"urgent": 0.87, "critical": 0.13},
            "confidence": 0.84,
        },
        "consciousness_concern": {
            "type": "choice",
            "choice": "no",
            "probabilities": {"no": 0.97, "yes": 0.03},
            "confidence": 0.96,
        },
        "breathing_concern": {
            "type": "choice",
            "choice": "uncertain",
            "probabilities": {"uncertain": 0.6, "no": 0.4},
            "confidence": 0.4,
        },
    },
    "usage": {"input_tokens": 612, "output_tokens": 80},
}


def test_normalize_valid_response():
    result = normalize_response(RAW_RESPONSE)
    assert result.model == "jev-1.13.0"
    assert result.error is None
    assert result.incident_type.value == "trauma"
    assert result.incident_type.confidence == 0.91
    assert result.incident_type.probabilities["bleeding"] == 0.05
    assert result.severity.value == "urgent"
    assert result.breathing_concern.value == "uncertain"


def test_normalize_missing_and_malformed_answers():
    raw = {
        "model": "jev-1.13.0",
        "answers": {
            "incident_type": {"type": "choice", "choice": "alien_abduction", "confidence": 0.99},
            "severity": {"type": "noul", "noul": 0.9},
            # consciousness_concern missing entirely
            "breathing_concern": "not a dict",
        },
    }
    result = normalize_response(raw)
    for name in CLASSIFICATION_FIELDS:
        label = getattr(result, name)
        assert label.value == "uncertain"
        assert label.confidence is None


def test_normalize_empty_response():
    result = normalize_response({})
    assert result.model is None
    assert all(getattr(result, n).value == "uncertain" for n in CLASSIFICATION_FIELDS)


def test_questions_use_our_label_sets():
    assert set(QUESTIONS["incident_type"]["criteria"]) == {
        "cardiac_or_circulatory", "respiratory", "trauma", "neurological", "bleeding", "other", "uncertain",
    }
    assert set(QUESTIONS["severity"]["criteria"]) == {"critical", "urgent", "non_urgent", "uncertain"}
    for name in ("consciousness_concern", "breathing_concern"):
        assert set(QUESTIONS[name]["criteria"]) == {"yes", "no", "uncertain"}
    assert all(q["type"] == "choice" for q in QUESTIONS.values())


def test_jev_state_contains_only_classification_inputs():
    state = IncidentState(
        session_id="secret-session",
        location="University of Twente",
        incident_description="Father collapsed.",
        conversation_summary="Caller's father collapsed and is not responding.",
        patient=PatientState(consciousness="unconscious"),
        number_of_patients=1,
    )
    transcript = [
        TranscriptEntry(speaker="agent", text="Is he breathing?"),
        TranscriptEntry(speaker="user", text="He's making strange noises."),
    ]
    jev_state = build_jev_state(state, transcript)
    assert set(jev_state) == {
        "incident_description", "conversation_summary", "patient", "number_of_patients", "call_transcript",
    }
    assert "University of Twente" not in str(jev_state)
    assert "secret-session" not in str(jev_state)
    assert jev_state["call_transcript"][1] == "Caller: He's making strange noises."

    request = build_request(jev_state, "jev-latest")
    assert request["model"] == "jev-latest"
    assert request["state"] is jev_state
