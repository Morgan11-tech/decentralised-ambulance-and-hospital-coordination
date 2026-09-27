import pytest
from pydantic import ValidationError

from export_schema import SCHEMA_PATH, incident_schema_json
from models.incident import ClassificationSummary, Incident, Location, PatientState


def make_incident(**overrides) -> Incident:
    data = dict(
        session_id="s-1",
        location=Location(raw_text="University of Twente"),
        incident_description="Cyclist fell and hit his head.",
        incident_type="trauma",
        severity="urgent",
        patient=PatientState(consciousness="conscious", breathing="normal", bleeding="present"),
        number_of_patients=1,
        classification=ClassificationSummary(
            incident_type_confidence=0.91,
            severity_confidence=0.84,
            consciousness_concern="no",
            consciousness_concern_confidence=0.96,
            breathing_concern="no",
            breathing_concern_confidence=0.92,
            classifier="jev-1.13.0",
        ),
        source="voice_agent",
    )
    data.update(overrides)
    return Incident(**data)


def test_valid_incident_defaults():
    incident = make_incident()
    assert incident.status == "ready_for_dispatch"
    assert incident.schema_version == "1.0"
    assert len(incident.incident_id) == 36
    assert incident.created_at.tzinfo is not None


def test_json_round_trip():
    incident = make_incident()
    payload = incident.model_dump(mode="json")
    assert payload["created_at"].endswith("Z")
    assert Incident.model_validate(payload) == incident


@pytest.mark.parametrize(
    "overrides",
    [
        {"incident_type": "heart_attack"},  # not an allowed label
        {"severity": "A1"},  # no Dutch urgency codes
        {"number_of_patients": 0},
        {"incident_description": ""},
        {"source": "somewhere_else"},
        {"location": {"raw_text": "x", "latitude": 123.0}},
    ],
)
def test_invalid_values_are_rejected(overrides):
    with pytest.raises(ValidationError):
        make_incident(**overrides)


def test_unknown_fields_are_rejected():
    payload = make_incident().model_dump(mode="json")
    payload["debug"] = {"anything": True}
    with pytest.raises(ValidationError):
        Incident.model_validate(payload)


def test_synthetic_generator_can_produce_same_schema():
    incident = make_incident(
        session_id=None,
        location=Location(raw_text=None, latitude=52.24, longitude=6.85),
        classification=ClassificationSummary(classifier="synthetic"),
        source="synthetic_generator",
    )
    assert incident.classification.incident_type_confidence is None


def test_exported_schema_file_is_up_to_date():
    assert SCHEMA_PATH.exists(), "run: python export_schema.py"
    assert SCHEMA_PATH.read_text() == incident_schema_json(), "run: python export_schema.py"
