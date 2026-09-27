"""Our own, provider-independent classification format.

`services/jev_service.py` converts Jev's API response into these models, so the
rest of the application never touches Jev-specific JSON.
"""

from pydantic import BaseModel, Field

# The four classifications we ask Jev for, in a fixed order.
CLASSIFICATION_FIELDS = (
    "incident_type",
    "severity",
    "consciousness_concern",
    "breathing_concern",
)


class LabelResult(BaseModel):
    value: str = "uncertain"
    confidence: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)

    def is_confident(self, threshold: float) -> bool:
        """A label is accepted only if it is a real answer with enough confidence."""
        return (
            self.value != "uncertain"
            and self.confidence is not None
            and self.confidence >= threshold
        )

    def final_value(self, threshold: float) -> str:
        """The label we store: low-confidence answers become "uncertain"."""
        return self.value if self.is_confident(threshold) else "uncertain"


class ClassificationResult(BaseModel):
    incident_type: LabelResult = Field(default_factory=LabelResult)
    severity: LabelResult = Field(default_factory=LabelResult)
    consciousness_concern: LabelResult = Field(default_factory=LabelResult)
    breathing_concern: LabelResult = Field(default_factory=LabelResult)
    model: str | None = None
    error: str | None = None

    def uncertain_fields(self, threshold: float) -> list[str]:
        """Classifications that were not accepted (candidates for a clarification question)."""
        return [
            name
            for name in CLASSIFICATION_FIELDS
            if not getattr(self, name).is_confident(threshold)
        ]

    @classmethod
    def unavailable(cls, error: str) -> "ClassificationResult":
        """Used when Jev cannot be reached: every label is "uncertain"."""
        return cls(error=error)
