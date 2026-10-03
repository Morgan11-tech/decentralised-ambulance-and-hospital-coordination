import json

import pytest
from pydantic import ValidationError

from config import PROJECT_ROOT
from export_schema import SCHEMA_PATH, incident_schema_json
from models.incident import Incident

SAMPLE_PATH = PROJECT_ROOT / "examples" / "sample_incident.json"


def sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text())


def test_sample_incident_uses_the_production_schema():
    incident = Incident.model_validate(sample())
    assert incident.status == "ready_for_dispatch"
    assert incident.incident.type == "trauma" and incident.incident.severity == "urgent"
    # the sample must not pretend to contain real Jev measurements
    assert all(label["confidence"] is None for label in sample()["classification"].values())


def test_json_round_trip_is_stable():
    incident = Incident.model_validate(sample())
    payload = incident.model_dump(mode="json")
    assert list(payload) == [
        "schema_version", "incident_id", "session_id", "created_at", "source",
        "location", "incident", "patients", "scene", "classification", "status",
    ]
    assert payload["created_at"].endswith("Z")
    assert Incident.model_validate(payload) == incident


def test_defaults():
    data = sample()
    del data["incident_id"], data["created_at"]
    incident = Incident.model_validate(data)
    assert incident.incident_id.startswith("INC-") and len(incident.incident_id) == 16
    assert incident.created_at.tzinfo is not None


@pytest.mark.parametrize(
    "path, value",
    [
        (("incident", "type"), "heart_attack"),  # not an allowed label
        (("incident", "severity"), "A1"),  # no Dutch urgency codes
        (("patients", "count"), 0),
        (("incident", "description"), ""),
        (("source",), "somewhere_else"),
        (("location", "latitude"), 123.0),
        (("patients", "primary_patient", "consciousness"), "altered"),
        (("patients", "primary_patient", "severe_bleeding"), "not_relevant"),
        (("scene", "entrapment"), "maybe"),
        (("classification", "severity", "confidence"), 1.4),
        (("status",), "collecting"),  # drafts are never valid incidents
    ],
)
def test_invalid_values_are_rejected(path, value):
    data = sample()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Incident.model_validate(data)


def test_type_and_severity_must_match_classification():
    data = sample()
    data["incident"]["severity"] = "critical"  # classification says urgent
    with pytest.raises(ValidationError, match="incident.severity"):
        Incident.model_validate(data)


def test_unknown_fields_are_rejected():
    data = sample()
    data["patients"]["primary_patient"]["diagnosis"] = "concussion"
    with pytest.raises(ValidationError):
        Incident.model_validate(data)


def test_synthetic_generator_can_produce_the_same_schema():
    data = sample()
    data.update(source="synthetic_generator", session_id=None)
    data["location"] = {"raw_text": None, "latitude": 52.2393, "longitude": 6.8556}
    assert Incident.model_validate(data).source == "synthetic_generator"


def test_exported_schema_file_is_up_to_date():
    assert SCHEMA_PATH.exists(), "run: python export_schema.py"
    assert SCHEMA_PATH.read_text() == incident_schema_json(), "run: python export_schema.py"
