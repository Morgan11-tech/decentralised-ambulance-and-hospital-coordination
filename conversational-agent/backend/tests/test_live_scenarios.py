"""Scenarios A–E against the REAL Gemini (and Jev). Opt-in, needs API keys:

    RUN_LIVE_TESTS=1 pytest tests/test_live_scenarios.py -s

Nothing is written to MongoDB. LLM output varies, so assertions are about
behaviour (what is extracted, what is not asked again), not exact wording.
"""

import os

import pytest

from intake_agent import IntakeAgent
from services import gemini_service

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_TESTS") != "1", reason="set RUN_LIVE_TESTS=1 to call real APIs")


@pytest.fixture(autouse=True)
def fresh_gemini_client():
    gemini_service._client = None  # its HTTP connections belong to the previous test's event loop
    yield
    gemini_service._client = None


async def _no_store(_incident, _metadata):
    return None


async def _ignore(_event):
    return None


async def talk(*caller_lines: str) -> tuple[IntakeAgent, list[str]]:
    agent = IntakeAgent("live-test", _ignore, store=_no_store)
    await agent.start()
    replies = []
    for line in caller_lines:
        if agent.done:
            break
        replies.append((await agent.handle_caller_text(line)).text)
        print(f"\nCaller: {line}\nAgent:  {replies[-1]}   asked={agent.state.asked_topics}")
    return agent, replies


async def test_a_does_not_repeat_known_information():
    agent, _ = await talk("I'm at the Vrijhof. My friend fell from his bike. He's conscious and breathing normally.")
    s = agent.state
    assert s.location.status == s.incident.description.status == "known"
    assert s.patient_state.consciousness.value == "conscious" and s.patient_state.breathing.value == "normal"
    assert not {"location", "what_happened", "consciousness", "breathing"} & set(s.asked_topics)


async def test_b_collapse_asks_one_highest_priority_question():
    agent, replies = await talk("My father collapsed.")
    assert agent.state.asked_topics == ["location"]
    assert replies[0].count("?") == 1


async def test_c_car_crash_extracts_count_and_entrapment():
    agent, _ = await talk("There's been a car crash at the Hengelosestraat. Three people are injured and one is trapped.")
    s = agent.state
    assert s.patients.count.value == 3
    assert s.scene.entrapment.value == "yes"
    assert not {"location", "what_happened", "patient_count", "entrapment"} & set(s.asked_topics)


async def test_d_symptoms_not_diagnosis_and_neurological_label():
    agent, _ = await talk(
        "My husband can't move his left arm and his speech sounds strange. We're at home at Calslaan 12 in Enschede.",
        "Yes, he is awake and breathing normally.",
        "No.",
        "No.",
    )
    symptoms = " ".join(agent.state.patient_state.symptoms).lower()
    assert "arm" in symptoms and "speech" in symptoms
    assert "stroke" not in symptoms and "stroke" not in (agent.state.incident.description.value or "").lower()
    if agent.incident:
        assert agent.incident.incident.type in ("neurological", "uncertain")


async def test_e_weird_breathing_is_never_normal():
    agent, _ = await talk("My dad collapsed at the station and he's making weird breathing noises.")
    assert agent.state.patient_state.breathing.value != "normal"
