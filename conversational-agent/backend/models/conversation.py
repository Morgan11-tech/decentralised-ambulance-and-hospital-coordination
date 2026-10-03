"""Conversation models: the transcript and Gemini's structured per-turn output."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from models.incident import Breathing, Consciousness

StatusFlag = Literal["yes", "no", "unknown", "not_relevant"]


class TranscriptEntry(BaseModel):
    speaker: Literal["user", "agent"]
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _question(topic: str) -> object:
    return Field(
        default=None,
        description=f"Natural question to ask about {topic}, if it is still needed; otherwise null.",
    )


class GeminiTurn(BaseModel):
    """What Gemini returns after every caller utterance (structured output).

    1. Extraction: the full current picture of the incident (values learned in
       earlier turns included). The intake policy merges it into the working state.
    2. Phrasing: one natural question for each piece of information that is still
       needed. The backend, not Gemini, decides which one is asked.

    Kept flat (no nested objects) because it is sent to Gemini as a JSON Schema.
    """

    location: str | None = Field(description="Where the emergency is, in the caller's words. null if not stated.")
    incident_description: str | None = Field(
        description="One short factual sentence about what happened. null if the caller has not said."
    )
    mechanism: str | None = Field(
        description="How it happened in a few words (e.g. 'bicycle fall', 'car collision'). null if not stated or not applicable."
    )
    patient_count: int | None = Field(
        description="Number of patients. 1 when the caller clearly talks about one person. null if unclear."
    )
    consciousness: Consciousness = Field(
        description="conscious = awake/responding (also if talking); unconscious = not responding; unknown = not stated."
    )
    breathing: Breathing = Field(
        description="normal; abnormal = struggling, gasping, noisy or strange breathing; not_breathing; unknown = not stated."
    )
    severe_bleeding: Literal["present", "absent", "unknown", "not_relevant"] = Field(
        description="present = heavy or uncontrolled bleeding; absent = no bleeding or only minor bleeding; "
        "unknown = bleeding is relevant but its severity is not known; not_relevant = no injury or bleeding involved."
    )
    entrapment: StatusFlag = Field(
        description="Is anyone trapped? not_relevant unless a vehicle collision, machinery or collapsed structure is involved."
    )
    immediate_danger: StatusFlag = Field(
        description="Immediate danger at the scene (traffic, fire, smoke, gas, electricity, water, violence)? "
        "not_relevant for ordinary medical incidents."
    )
    symptoms: list[str] = Field(
        description="Caller observations in plain words, e.g. 'head injury', 'left arm weakness', 'speech difficulty'. "
        "Never a diagnosis."
    )
    conversation_summary: str = Field(description="Two or three factual sentences summarising everything the caller said.")
    preface: str | None = Field(
        description="Optional very short acknowledgement to say before the next question (e.g. 'Help is being arranged.'). Usually null."
    )

    question_location: str | None = _question("the location")
    question_what_happened: str | None = _question("what happened")
    question_consciousness: str | None = _question("whether the patient responds")
    question_breathing: str | None = _question("whether the patient breathes normally")
    question_severe_bleeding: str | None = _question("severe bleeding")
    question_patient_count: str | None = _question("how many people are hurt")
    question_entrapment: str | None = _question("whether anyone is trapped")
    question_immediate_danger: str | None = _question("immediate danger at the scene")

    def question_for(self, topic: str) -> str | None:
        text = getattr(self, f"question_{topic}")
        return text.strip() if text and text.strip() else None


class ClarificationQuestion(BaseModel):
    question: str = Field(description="One short, natural clarification question to ask the caller.")
