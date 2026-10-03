"""Shared fakes: scripted Gemini extraction, Jev results and a recording MongoDB store."""

from config import Settings
from intake_agent import IntakeAgent
from intake_policy import TOPIC_PRIORITY
from models.classification import ClassificationResult, LabelResult
from models.conversation import GeminiTurn
from models.incident import Incident

SETTINGS = Settings(_env_file=None, jev_confidence_threshold=0.7, max_classification_clarifications=1)


def ask(topic: str) -> str:
    """The question text our fake Gemini phrases for a topic (easy to assert on)."""
    return f"[ask {topic}]"


def turn(**fields) -> GeminiTurn:
    """A Gemini extraction. Unspecified facts are unknown / not relevant; every topic gets a phrasing."""
    data = dict(
        location=None,
        incident_description=None,
        mechanism=None,
        patient_count=None,
        consciousness="unknown",
        breathing="unknown",
        severe_bleeding="unknown",
        entrapment="not_relevant",
        immediate_danger="not_relevant",
        symptoms=[],
        conversation_summary="",
        preface=None,
        **{f"question_{t}": ask(t) for t in TOPIC_PRIORITY},
    )
    data.update(fields)
    return GeminiTurn(**data)


def classification(conf: float = 0.9, breathing_conf: float | None = None, model="jev-1.13.0"):
    return ClassificationResult(
        incident_type=LabelResult(value="trauma", confidence=conf),
        severity=LabelResult(value="urgent", confidence=conf),
        consciousness_concern=LabelResult(value="no", confidence=conf),
        breathing_concern=LabelResult(value="no", confidence=conf if breathing_conf is None else breathing_conf),
        model=model,
    )


class Fakes:
    def __init__(self, turns, results=(), clarifications=(), store_error: Exception | None = None):
        self.turns = list(turns)
        self.results = list(results)
        self.clarifications = list(clarifications)
        self.store_error = store_error
        self.prompts: list[str] = []
        self.clarification_prompts: list[str] = []
        self.stored: list[tuple[Incident, dict]] = []
        self.events: list[dict] = []
        self.jev_calls = 0

    async def llm(self, prompt):
        self.prompts.append(prompt)
        item = self.turns.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def clarifier(self, prompt):
        self.clarification_prompts.append(prompt)
        item = self.clarifications.pop(0) if self.clarifications else "Is he breathing normally right now?"
        if isinstance(item, Exception):
            raise item
        return item

    async def classifier(self, state, transcript):
        self.jev_calls += 1
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item, {"model": item.model, "answers": {}}

    async def store(self, incident, metadata):
        if self.store_error:
            raise self.store_error
        self.stored.append((incident, metadata))

    async def emit(self, event):
        self.events.append(event)

    def agent_kwargs(self) -> dict:
        return dict(llm=self.llm, clarifier=self.clarifier, classifier=self.classifier, store=self.store, settings=SETTINGS)

    def agent(self) -> IntakeAgent:
        return IntakeAgent("session-1", self.emit, **self.agent_kwargs())

    def events_of(self, kind):
        return [e for e in self.events if e["type"] == kind]
