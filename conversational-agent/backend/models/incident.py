"""Incident models.

Two kinds of incident model live here:

* `IncidentState`: the *working* state that the intake conversation fills in.
  It may be incomplete and uses "unknown" freely.

* `Incident`: the *canonical* payload handed to the downstream Multi-Agent
  System. The voice agent and the (future) synthetic incident generator must
  both produce exactly this model, so the MAS never needs to know where an
  incident came from. `schemas/incident.schema.json` is generated from it.

All classifications are SIMULATION labels for research. They are not clinical
triage and are not mapped to Dutch A0/A1/A2 ambulance urgency codes.
"""

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# --- Patient observations (what the caller told us) ----------------------------
Consciousness = Literal["conscious", "altered", "unconscious", "unknown"]
Breathing = Literal["normal", "abnormal", "not_breathing", "unknown"]
Bleeding = Literal["none", "present", "severe", "unknown"]

# --- Jev classification labels ---------------------------------------------------
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
IntakeStatus = Literal["collecting", "classifying", "clarifying", "completed"]


class PatientState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consciousness: Consciousness = "unknown"
    breathing: Breathing = "unknown"
    bleeding: Bleeding = "unknown"


class IncidentState(BaseModel):
    """Working state maintained during the conversation."""

    session_id: str
    location: str | None = None
    incident_description: str | None = None
    conversation_summary: str | None = None
    patient: PatientState = Field(default_factory=PatientState)
    number_of_patients: int | None = None
    incident_type: IncidentType | Literal["unknown"] = "unknown"
    severity: Severity | Literal["unknown"] = "unknown"
    status: IntakeStatus = "collecting"


# --- Canonical payload ---------------------------------------------------------


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ClassificationSummary(BaseModel):
    """Classifier output that downstream agents may want to reason about.

    Confidences are 0..1, or null when no classifier confidence exists
    (e.g. Jev was unavailable, or the incident was generated synthetically).
    """

    model_config = ConfigDict(extra="forbid")

    incident_type_confidence: float | None = Field(default=None, ge=0, le=1)
    severity_confidence: float | None = Field(default=None, ge=0, le=1)
    consciousness_concern: Concern = "uncertain"
    consciousness_concern_confidence: float | None = Field(default=None, ge=0, le=1)
    breathing_concern: Concern = "uncertain"
    breathing_concern_confidence: float | None = Field(default=None, ge=0, le=1)
    classifier: str = Field(
        description='What produced the labels, e.g. "jev-1.13.0", "unavailable" or "synthetic".'
    )


class Incident(BaseModel):
    """Canonical incident payload consumed by the Multi-Agent System."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    incident_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    location: Location
    incident_description: str = Field(min_length=1)
    incident_type: IncidentType
    severity: Severity
    patient: PatientState
    number_of_patients: int | None = Field(default=None, ge=1)
    classification: ClassificationSummary
    source: IncidentSource
    status: Literal["ready_for_dispatch"] = "ready_for_dispatch"
