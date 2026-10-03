"""Conversation flows of the intake agent, using fake Gemini / Jev / MongoDB."""

import pytest

from intake_agent import MAX_INTAKE_QUESTIONS, AgentError
from intake_policy import TOPIC_PRIORITY
from models.classification import ClassificationResult
from prompts.emergency_agent import CLOSING_MESSAGE, GREETING
from tests.fakes import Fakes, ask, classification, turn

VRIJHOF = dict(
    location="Outside the Vrijhof, University of Twente",
    incident_description="Friend fell off his bike and hit his head.",
    mechanism="bicycle fall",
    patient_count=1,
    consciousness="conscious",
    symptoms=["head injury", "bleeding"],
)


async def test_example_from_the_spec_asks_only_what_is_missing():
    # Caller gives location, what happened, consciousness and bleeding in one go.
    fakes = Fakes(
        turns=[
            turn(**VRIJHOF),  # "...He's awake but bleeding."
            turn(**VRIJHOF, breathing="normal"),  # "Yes."
            turn(**VRIJHOF, breathing="normal", severe_bleeding="absent"),  # "Not much."
        ],
        results=[classification(0.9)],
    )
    agent = fakes.agent()
    assert (await agent.start()).text == GREETING == "112 emergency assistance. Where is the emergency?"

    reply = await agent.handle_caller_text("I'm outside the Vrijhof. My friend fell off his bike and hit his head. He's awake but bleeding.")
    assert reply.text == ask("breathing")  # not location / what happened / consciousness
    reply = await agent.handle_caller_text("Yes.")
    assert reply.text == ask("severe_bleeding")
    reply = await agent.handle_caller_text("No, it's not much.")
    assert reply.done and reply.text == CLOSING_MESSAGE

    asked = [t.text for t in agent.transcript if t.speaker == "agent"]
    for topic in ("location", "what_happened", "consciousness"):
        assert ask(topic) not in asked
    incident, metadata = fakes.stored[0]
    assert incident.patients.primary_patient.breathing == "normal"
    assert metadata["working_state"]["asked_topics"] == ["breathing", "severe_bleeding"]
    assert metadata["working_state"]["patient_state"]["breathing"]["source_turn"] == 2


async def test_collapse_flow_one_question_at_a_time():
    collapse = dict(incident_description="Father suddenly collapsed.", patient_count=1, severe_bleeding="not_relevant")
    fakes = Fakes(
        turns=[
            turn(**collapse),
            turn(**collapse, location="University of Twente"),
            turn(**collapse, location="University of Twente", consciousness="unconscious"),
            turn(**collapse, location="University of Twente", consciousness="unconscious", breathing="abnormal"),
        ],
        results=[classification(0.95)],
    )
    agent = fakes.agent()
    await agent.start()
    replies = [
        (await agent.handle_caller_text(text)).text
        for text in ["My father collapsed.", "We are at the University of Twente.", "He isn't responding.", "He's gasping."]
    ]
    assert replies == [ask("location"), ask("consciousness"), ask("breathing"), CLOSING_MESSAGE]
    assert fakes.jev_calls == 1


async def test_state_and_draft_json_are_emitted_every_turn():
    fakes = Fakes(turns=[turn(incident_description="Father collapsed."), turn(incident_description="Father collapsed.", location="UT")])
    agent = fakes.agent()
    await agent.start()
    await agent.handle_caller_text("My father collapsed.")
    await agent.handle_caller_text("At the UT.")

    states = fakes.events_of("incident_state")
    assert len(states) == 3  # greeting + two caller turns
    assert states[0]["next_topic"] == "location" and states[0]["incident"]["incident"]["description"] is None
    assert states[1]["incident"]["incident"]["description"] == "Father collapsed."
    assert states[1]["next_topic"] == "location"
    assert states[2]["incident"]["location"]["raw_text"] == "UT"
    assert states[2]["next_topic"] == "consciousness"
    assert {t["topic"] for t in states[2]["topics"]} == set(TOPIC_PRIORITY)


async def test_jev_results_enrich_the_live_state():
    fakes = Fakes(turns=[turn(**VRIJHOF, breathing="normal", severe_bleeding="absent")], results=[classification(0.9)])
    agent = fakes.agent()
    await agent.start()
    await agent.handle_caller_text("Everything at once.")

    states = fakes.events_of("incident_state")
    before, after_jev = states[1], states[2]
    assert before["incident"]["incident"]["type"] == "unknown"
    assert after_jev["incident"]["incident"]["type"] == "trauma"
    assert after_jev["incident"]["classification"]["severity"] == {"value": "urgent", "confidence": 0.9}
    assert states[-1]["incident"]["status"] == "ready_for_dispatch"


async def test_low_confidence_asks_one_clarification_then_stores_uncertain():
    weird = dict(location="Station", incident_description="Man collapsed.", patient_count=1,
                 consciousness="unconscious", breathing="abnormal", severe_bleeding="not_relevant")
    fakes = Fakes(
        turns=[turn(**weird), turn(**weird)],
        results=[classification(0.9, breathing_conf=0.4), classification(0.9, breathing_conf=0.5)],
        clarifications=["Is he breathing normally right now?"],
    )
    agent = fakes.agent()
    await agent.start()

    reply = await agent.handle_caller_text("He's making weird breathing noises.")
    assert reply.text == "Is he breathing normally right now?" and not reply.done
    assert agent.state.status == "clarifying"
    assert "breathing normally right now" in fakes.clarification_prompts[0]

    reply = await agent.handle_caller_text("I'm not sure.")
    assert reply.done
    assert fakes.jev_calls == 2 and agent.clarifications_used == 1
    assert agent.incident.classification.breathing_concern.value == "uncertain"
    assert agent.incident.classification.breathing_concern.confidence == 0.5


async def test_clarification_falls_back_if_gemini_fails():
    done = dict(VRIJHOF, breathing="normal", severe_bleeding="absent")
    fakes = Fakes(turns=[turn(**done)], results=[classification(0.9, breathing_conf=0.4)], clarifications=[RuntimeError("down")])
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("All at once.")
    assert reply.text == "Is the patient breathing normally right now?"


async def test_jev_unavailable_does_not_break_conversation():
    fakes = Fakes(turns=[turn(**VRIJHOF, breathing="normal", severe_bleeding="absent")],
                  results=[ClassificationResult.unavailable("Jev HTTP 503")])
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("All at once.")
    assert reply.done  # no pointless clarification during an outage
    assert agent.incident.incident.type == "uncertain"
    assert agent.incident.classification.incident_type.confidence is None
    assert any(e["source"] == "jev" for e in fakes.events_of("error"))
    assert agent.persisted


async def test_jev_exception_does_not_break_conversation():
    fakes = Fakes(turns=[turn(**VRIJHOF, breathing="normal", severe_bleeding="absent")], results=[TypeError("bad json")])
    agent = fakes.agent()
    await agent.start()
    assert (await agent.handle_caller_text("All at once.")).done
    assert agent.incident.incident.severity == "uncertain"


async def test_mongodb_failure_keeps_incident_in_memory():
    fakes = Fakes(turns=[turn(**VRIJHOF, breathing="normal", severe_bleeding="absent")], results=[classification(0.9)],
                  store_error=ConnectionError("no route to host"))
    agent = fakes.agent()
    await agent.start()
    assert (await agent.handle_caller_text("All at once.")).done
    assert agent.incident is not None and agent.persisted is False
    complete = fakes.events_of("incident_complete")[0]
    assert complete["persisted"] is False and complete["incident"]["incident"]["type"] == "trauma"


async def test_gemini_failure_can_be_retried():
    fakes = Fakes(turns=[RuntimeError("503"), turn(incident_description="Dad collapsed.")])
    agent = fakes.agent()
    await agent.start()
    with pytest.raises(AgentError) as exc_info:
        await agent.handle_caller_text("My dad collapsed.")
    assert exc_info.value.source == "gemini" and agent.awaiting_reply

    reply = await agent.retry()
    assert reply.text == ask("location")
    assert [t.text for t in agent.transcript].count("My dad collapsed.") == 1


async def test_missing_gemini_phrasing_uses_fallback_and_preface():
    fakes = Fakes(turns=[turn(incident_description="Dad collapsed.", question_location=None, preface="Help is being arranged.")])
    agent = fakes.agent()
    await agent.start()
    reply = await agent.handle_caller_text("Please hurry, my dad collapsed!")
    assert reply.text == "Help is being arranged. Where is the emergency?"


async def test_caller_who_knows_nothing_ends_after_each_topic_once():
    everything_relevant = dict(entrapment="unknown", immediate_danger="unknown")
    fakes = Fakes(turns=[turn(**everything_relevant)] * (len(TOPIC_PRIORITY) + 1), results=[classification(0.9)])
    agent = fakes.agent()
    await agent.start()
    for topic in TOPIC_PRIORITY:
        assert (await agent.handle_caller_text("I don't know.")).text == ask(topic)
    assert (await agent.handle_caller_text("I don't know.")).done
    assert agent.questions_asked <= MAX_INTAKE_QUESTIONS


async def test_force_finalize():
    fakes = Fakes(turns=[turn(incident_description="Dad collapsed.")], results=[classification(0.9)])
    agent = fakes.agent()
    await agent.start()
    assert await agent.force_finalize() is False  # nothing known yet

    await agent.handle_caller_text("My dad collapsed.")
    assert await agent.force_finalize() is True
    assert agent.done and len(fakes.stored) == 1
    assert fakes.stored[0][0].location.raw_text is None  # unknown is acceptable
