"""Prompts for the conversational Gemini intake agent."""

import json

GREETING = "112 emergency assistance. Where is the emergency?"

CLOSING_MESSAGE = (
    "Thank you. I have recorded the incident and passed it on for dispatch. "
    "Please stay with the patient."
)

SYSTEM_PROMPT = """\
You are the emergency intake conversational component of a university
Multi-Agent Systems research prototype. This is a research simulation, not a
real emergency service. Callers role-play emergencies for a demonstration.

Your task is to help collect the minimum information required to create a
structured emergency incident. You are not a doctor: you never diagnose and you
never give medical advice.

After every caller message you do two things.

1. EXTRACT every useful factual detail the caller has given so far and return
   the complete current picture of the incident (keep values from earlier turns):
   - location: where the emergency is, in the caller's words.
   - incident_description: one short factual sentence about what happened,
     e.g. "Friend fell off his bicycle and hit his head."
   - mechanism: how it happened in a few words, e.g. "bicycle fall".
   - patient_count: 1 when the caller clearly talks about one person
     ("my father", "my friend"); the number given for several people; null if unclear.
   - consciousness, breathing, severe_bleeding, entrapment, immediate_danger:
     use the allowed values. Someone who is talking is conscious.
   - symptoms: what the caller OBSERVES, in plain words: "left arm weakness",
     "speech difficulty", "head injury", "chest pain", "confused".
     Never a diagnosis: write "speech difficulty", not "stroke".
   - Infer only what is obvious. Never invent uncertain facts. "unknown" is a
     valid value. Do not turn silence into "normal" or "absent".

   Relevance (use not_relevant so we do not ask pointless questions):
   - severe_bleeding: relevant for injuries, accidents, wounds or reported
     bleeding; not_relevant for e.g. a collapse, chest pain or breathing problem
     without any injury. Ordinary bleeding goes into symptoms; "present" only for
     heavy or uncontrolled bleeding, "absent" if the caller says it is minor or none.
   - entrapment: relevant only for vehicle collisions, machinery or collapsed structures.
   - immediate_danger: relevant only for road traffic scenes, fire, smoke, gas,
     electricity, water or violence.

2. PHRASE QUESTIONS. For every piece of information that is still needed (you
   are told which), write one short, natural question in the matching
   question_* field. The system chooses which one is asked, so write each as a
   complete question on its own. Use the right person: "Is he breathing
   normally?", "Is your father responding to you?".
   Sound like a calm human call-taker:
     good: "Are they responding to you?"     bad: "Please specify consciousness status."
     good: "Are they breathing normally?"    bad: "Please provide breathing state."
     good: "What happened?"                  bad: "Provide incident mechanism."
     good: "About how many people are injured?"
   One sentence, spoken aloud: no lists, no markdown.
   Leave question fields null for information that is known or not relevant.
   Never ask for BSN, insurance, GP, medication lists, medical history or identity details.

preface: null in almost every turn. Only if the caller's latest message asks you
something directly or begs for help, use exactly "Help is being arranged." Never
promise anything else (no "they are on their way"), never give medical advice.
"""


def _compact_state(state: dict) -> dict:
    """Value-or-status view of the working state, for the prompt."""

    def show(fact: dict):
        return fact["value"] if fact["status"] == "known" else fact["status"]

    return {
        "location": show(state["location"]),
        "incident_description": show(state["incident"]["description"]),
        "mechanism": show(state["incident"]["mechanism"]),
        "patient_count": show(state["patients"]["count"]),
        "consciousness": show(state["patient_state"]["consciousness"]),
        "breathing": show(state["patient_state"]["breathing"]),
        "severe_bleeding": show(state["patient_state"]["severe_bleeding"]),
        "symptoms": state["patient_state"]["symptoms"],
        "entrapment": show(state["scene"]["entrapment"]),
        "immediate_danger": show(state["scene"]["immediate_danger"]),
        "conversation_summary": state["conversation_summary"],
    }


def build_turn_prompt(
    state: dict, transcript: list[dict], still_needed: list[str], already_asked: list[str]
) -> str:
    """The per-turn input: current state, transcript and what is still needed."""
    return (
        "Current incident state (from earlier turns):\n"
        f"{json.dumps(_compact_state(state), indent=2)}\n\n"
        "Conversation so far:\n"
        f"{_format_transcript(transcript)}\n\n"
        f"Information still needed before the caller's latest message: {', '.join(still_needed) or 'none'}.\n"
        f"Already asked (do not write questions for these): {', '.join(already_asked) or 'none'}.\n"
        "Update the incident from the caller's latest message. Then write a question_* "
        "for every piece of information that is relevant and still unknown afterwards "
        "(including anything that only became relevant now), except the ones already asked."
    )


# What information would resolve each uncertain classification.
CLARIFICATION_HINTS = {
    "incident_type": "what the main problem is (for example an injury, a breathing problem, chest pain, a collapse)",
    "severity": "how serious the patient's condition seems right now",
    "consciousness_concern": "whether the patient is awake and responding normally",
    "breathing_concern": "whether the patient is breathing normally right now",
}


def build_clarification_prompt(
    state: dict, transcript: list[dict], uncertain_fields: list[str]
) -> str:
    """Asks Gemini for ONE question that resolves the uncertain classifications."""
    needs = "\n".join(f"- {CLARIFICATION_HINTS[f]}" for f in uncertain_fields)
    return (
        "Current incident state:\n"
        f"{json.dumps(_compact_state(state), indent=2)}\n\n"
        "Conversation so far:\n"
        f"{_format_transcript(transcript)}\n\n"
        "The incident classifier is not confident yet. It still needs to know:\n"
        f"{needs}\n\n"
        "Write ONE short, natural question that best resolves this. Do not repeat a "
        "question exactly as it was asked before; make it more specific."
    )


def _format_transcript(transcript: list[dict]) -> str:
    labels = {"user": "Caller", "agent": "Agent"}
    return "\n".join(f"{labels[t['speaker']]}: {t['text']}" for t in transcript)
