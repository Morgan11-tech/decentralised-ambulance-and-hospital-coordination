"""The live working state of one intake conversation.

Internal only: it carries bookkeeping (field status, which caller turn supplied a
value, which questions were asked) that the MAS must not depend on. The clean
`Incident` payload is built from it by `intake_policy.incident_payload`.
"""

from typing import Literal

from pydantic import BaseModel, Field

from models.incident import new_incident_id

FieldStatus = Literal["known", "unknown", "not_relevant"]
IntakeStatus = Literal["collecting", "classifying", "clarifying", "completed"]

# The pieces of information the intake may ask about (and nothing else).
Topic = Literal[
    "location",
    "what_happened",
    "consciousness",
    "breathing",
    "severe_bleeding",
    "patient_count",
    "entrapment",
    "immediate_danger",
]


class Fact(BaseModel):
    value: str | int | None = None  # set only when status is "known"
    status: FieldStatus = "unknown"
    source_turn: int | None = None  # caller turn (1, 2, ...) that supplied the value


def _not_relevant() -> Fact:
    return Fact(status="not_relevant")


class IncidentFacts(BaseModel):
    description: Fact = Field(default_factory=Fact)
    mechanism: Fact = Field(default_factory=Fact)


class PatientsFacts(BaseModel):
    count: Fact = Field(default_factory=Fact)


class PatientStateFacts(BaseModel):
    consciousness: Fact = Field(default_factory=Fact)
    breathing: Fact = Field(default_factory=Fact)
    severe_bleeding: Fact = Field(default_factory=Fact)
    symptoms: list[str] = Field(default_factory=list)


class SceneFacts(BaseModel):
    # Only relevant for e.g. collisions or dangerous scenes; Gemini switches them on.
    entrapment: Fact = Field(default_factory=_not_relevant)
    immediate_danger: Fact = Field(default_factory=_not_relevant)


class LabelView(BaseModel):
    value: str
    confidence: float | None = None


class WorkingState(BaseModel):
    session_id: str
    incident_id: str = Field(default_factory=new_incident_id)
    status: IntakeStatus = "collecting"

    location: Fact = Field(default_factory=Fact)
    incident: IncidentFacts = Field(default_factory=IncidentFacts)
    patients: PatientsFacts = Field(default_factory=PatientsFacts)
    patient_state: PatientStateFacts = Field(default_factory=PatientStateFacts)
    scene: SceneFacts = Field(default_factory=SceneFacts)
    conversation_summary: str | None = None

    # Filled in by Jev (simulation labels, already confidence-thresholded).
    incident_type: str = "unknown"
    severity: str = "unknown"
    classification: dict[str, LabelView] | None = None

    asked_topics: list[Topic] = Field(default_factory=list)

    def facts(self) -> dict[str, Fact]:
        """The Fact behind each askable topic."""
        return {
            "location": self.location,
            "what_happened": self.incident.description,
            "consciousness": self.patient_state.consciousness,
            "breathing": self.patient_state.breathing,
            "severe_bleeding": self.patient_state.severe_bleeding,
            "patient_count": self.patients.count,
            "entrapment": self.scene.entrapment,
            "immediate_danger": self.scene.immediate_danger,
        }
