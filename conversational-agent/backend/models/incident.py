"""Canonical Incident payload: the contract between incident sources (this voice
agent, the future synthetic generator) and the Multi-Agent (Mesa) simulation.

Everything here is source-independent: nothing voice-specific is required.
Documented in docs/incident-schema.md; JSON Schema in schemas/incident.schema.json
(regenerate with `python export_schema.py`).

Classifications are SIMULATION labels for research. They are not clinical triage
and are not Dutch A0/A1/A2 ambulance urgency codes.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

# --- Enums ------------------------------------------------------------------------
Consciousness = Literal["conscious", "unconscious", "unknown"]
Breathing = Literal["normal", "abnormal", "not_breathing", "unknown"]
SevereBleeding = Literal["present", "absent", "unknown"]
SceneFlag = Literal["yes", "no", "unknown", "not_relevant"]
IncidentType = Literal[
    "cardiac_or_circulatory",
    "respiratory",
    "trauma",
    "neurological",
    "bleeding",
    "other",
    "uncertain",
]
Severity = Literal["critical", "urgent", "non_urgent", "uncertain"]
Concern = Literal["yes", "no", "uncertain"]
IncidentSource = Literal["voice_agent", "synthetic_generator"]

def _confidence():
    return Field(
        default=None,
        ge=0,
        le=1,
        description="Classifier confidence 0..1; null when no confidence exists "
        "(classifier unavailable, or synthetic data).",
    )


def new_incident_id() -> str:
    return "INC-" + uuid4().hex[:12].upper()


class _Contract(BaseModel):
    # In the exported JSON Schema every key is required: payloads always carry all fields.
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Location(_Contract):
    raw_text: str | None = Field(default=None, description="Location as described, e.g. 'Vrijhof, University of Twente'.")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class IncidentDetails(_Contract):
    description: str = Field(min_length=1, description="One short factual sentence about what happened.")
    mechanism: str | None = Field(default=None, description="How it happened, e.g. 'bicycle fall'; null if not applicable/known.")
    type: IncidentType
    severity: Severity


class PatientCondition(_Contract):
    consciousness: Consciousness = "unknown"
    breathing: Breathing = "unknown"
    severe_bleeding: SevereBleeding = Field(
        default="unknown", description="present = heavy or uncontrolled bleeding reported."
    )
    symptoms: list[str] = Field(
        default_factory=list,
        description="Observations in plain words, e.g. 'head injury', 'left arm weakness'. Never diagnoses.",
    )


class Patients(_Contract):
    count: int | None = Field(default=None, ge=1, description="Number of patients; null if unknown.")
    primary_patient: PatientCondition = Field(
        default_factory=PatientCondition,
        description="The patient described, or the most seriously affected one when there are several.",
    )


class Scene(_Contract):
    entrapment: SceneFlag = "unknown"
    immediate_danger: SceneFlag = "unknown"


class IncidentTypeLabel(_Contract):
    value: IncidentType
    confidence: float | None = _confidence()


class SeverityLabel(_Contract):
    value: Severity
    confidence: float | None = _confidence()


class ConcernLabel(_Contract):
    value: Concern
    confidence: float | None = _confidence()


class Classification(_Contract):
    incident_type: IncidentTypeLabel
    severity: SeverityLabel
    consciousness_concern: ConcernLabel
    breathing_concern: ConcernLabel


class Incident(_Contract):
    """Canonical incident payload consumed by the Multi-Agent System."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    incident_id: str = Field(default_factory=new_incident_id, min_length=1)
    session_id: str | None = Field(default=None, description="Voice session id; null for synthetic incidents.")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: IncidentSource
    location: Location
    incident: IncidentDetails
    patients: Patients
    scene: Scene
    classification: Classification
    status: Literal["ready_for_dispatch"] = "ready_for_dispatch"

    @model_validator(mode="after")
    def _labels_match_classification(self) -> "Incident":
        if self.incident.type != self.classification.incident_type.value:
            raise ValueError("incident.type must equal classification.incident_type.value")
        if self.incident.severity != self.classification.severity.value:
            raise ValueError("incident.severity must equal classification.severity.value")
        return self
