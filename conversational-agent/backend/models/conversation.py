"""Conversation models: the transcript and Gemini's structured per-turn output."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from models.incident import Bleeding, Breathing, Consciousness


class TranscriptEntry(BaseModel):
    speaker: Literal["user", "agent"]
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GeminiTurn(BaseModel):
    """What Gemini returns after every caller utterance (structured output).

    Gemini returns the *full* current picture of the incident each turn; the
    intake agent merges it into the working state (see `merge_gemini_turn`).
    The schema is kept flat because it is sent to Gemini as a JSON Schema.
    """

    location: str | None = Field(
        description="Where the emergency is, in the caller's words. null if not stated."
    )
    incident_description: str | None = Field(
        description="One short factual sentence describing what happened. null if unclear."
    )
    number_of_patients: int | None = Field(
        description="How many people need help. null if not stated."
    )
    consciousness: Consciousness = Field(
        description="conscious = awake and responding; altered = confused/drowsy; "
        "unconscious = not responding; unknown = the caller has not said."
    )
    breathing: Breathing = Field(
        description="normal; abnormal = struggling, noisy, gasping; not_breathing; "
        "unknown = the caller has not said."
    )
    bleeding: Bleeding = Field(
        description="none = the caller explicitly said there is no bleeding; present = some bleeding; "
        "severe = heavy or will not stop; unknown = bleeding has not been mentioned."
    )
    conversation_summary: str = Field(
        description="Two or three factual sentences summarising everything the caller has said."
    )
    ready_for_classification: bool = Field(
        description="true when enough information has been collected to create the incident."
    )
    reply: str = Field(
        description="What the agent says next: one short, calm sentence, usually a single question."
    )
