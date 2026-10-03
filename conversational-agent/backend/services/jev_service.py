import asyncio

import httpx

from config import get_settings
from models.classification import CLASSIFICATION_FIELDS, ClassificationResult, LabelResult
from models.conversation import TranscriptEntry
from models.working_state import Fact, WorkingState

_UNCERTAIN = "The information provided is not enough to decide."

# Each question is a Choice. We include an explicit "uncertain" option so Jev
# can say "not enough information" instead of being forced to guess; low
# confidence on any other option is also treated as uncertain (see
# LabelResult.final_value).
QUESTIONS = {
    "incident_type": {
        "type": "choice",
        "instructions": "What is the main type of this simulated emergency incident?",
        "criteria": {
            "cardiac_or_circulatory": "Heart or circulation problem: chest pain, cardiac arrest, "
            "sudden collapse with suspected heart cause, fainting from circulation problems.",
            "respiratory": "Breathing problem as the main issue: asthma attack, choking, "
            "severe shortness of breath.",
            "trauma": "Physical injury from an external cause: fall, traffic accident, "
            "sports injury, blow to the head.",
            "neurological": "Brain or nerve problem: stroke symptoms, seizure, sudden confusion "
            "or unresponsiveness without an injury.",
            "bleeding": "Bleeding is the main problem and there is no other major injury.",
            "other": "A medical emergency that fits none of the other categories.",
            "uncertain": _UNCERTAIN,
        },
    },
    "severity": {
        "type": "choice",
        "instructions": "How severe is the patient's condition for this simulation?",
        "criteria": {
            "critical": "Immediately life-threatening: unconscious, not breathing or breathing "
            "abnormally, or severe bleeding.",
            "urgent": "Serious and needs help soon, but the patient is conscious and breathing.",
            "non_urgent": "Minor problem; the patient is stable.",
            "uncertain": _UNCERTAIN,
        },
    },
    "consciousness_concern": {
        "type": "choice",
        "instructions": "Is there a concern about the patient's level of consciousness?",
        "criteria": {
            "yes": "The patient is unconscious, unresponsive, confused or drowsy.",
            "no": "The patient is awake, alert and responding normally.",
            "uncertain": _UNCERTAIN,
        },
    },
    "breathing_concern": {
        "type": "choice",
        "instructions": "Is there a concern about the patient's breathing?",
        "criteria": {
            "yes": "The patient is not breathing, or is breathing abnormally "
            "(gasping, struggling, noisy or strange breathing sounds).",
            "no": "The patient is breathing normally.",
            "uncertain": _UNCERTAIN,
        },
    },
}


def _show(fact: Fact):
    return fact.value if fact.status == "known" else fact.status  # "unknown" / "not_relevant"


def build_jev_state(state: WorkingState, transcript: list[TranscriptEntry]) -> dict:
    """The structured factual state relevant to classification (no location, ids, bookkeeping)."""
    return {
        "incident_description": _show(state.incident.description),
        "mechanism": _show(state.incident.mechanism),
        "patient_state": {
            "consciousness": _show(state.patient_state.consciousness),
            "breathing": _show(state.patient_state.breathing),
            "severe_bleeding": _show(state.patient_state.severe_bleeding),
        },
        "symptoms": state.patient_state.symptoms,
        "number_of_patients": _show(state.patients.count),
        "scene": {
            "entrapment": _show(state.scene.entrapment),
            "immediate_danger": _show(state.scene.immediate_danger),
        },
        "conversation_summary": state.conversation_summary,
        "call_transcript": [
            f"{'Caller' if t.speaker == 'user' else 'Call-taker'}: {t.text}" for t in transcript
        ],
    }


def build_request(jev_state: dict, model: str) -> dict:
    return {"model": model, "state": jev_state, "questions": QUESTIONS}


def normalize_response(raw: dict) -> ClassificationResult:
    """Convert Jev's response JSON into our ClassificationResult.

    Missing or malformed answers become "uncertain" with no confidence.
    """
    answers = raw.get("answers") or {}
    labels: dict[str, LabelResult] = {}
    for name in CLASSIFICATION_FIELDS:
        answer = answers.get(name)
        allowed = QUESTIONS[name]["criteria"]
        if (
            not isinstance(answer, dict)
            or answer.get("type") != "choice"
            or answer.get("choice") not in allowed
        ):
            labels[name] = LabelResult()
            continue
        confidence = answer.get("confidence")
        labels[name] = LabelResult(
            value=answer["choice"],
            confidence=float(confidence) if confidence is not None else None,
            probabilities={k: float(v) for k, v in (answer.get("probabilities") or {}).items()},
        )
    return ClassificationResult(**labels, model=raw.get("model"))


async def classify(
    state: WorkingState, transcript: list[TranscriptEntry]
) -> tuple[ClassificationResult, dict | None]:
    """Run the four classifications. Never raises: on failure every label is
    "uncertain" and `result.error` explains why. Returns (result, raw_response)."""
    settings = get_settings()
    if not settings.jev_api_key:
        return ClassificationResult.unavailable("JEV_API_KEY is not set"), None

    body = build_request(build_jev_state(state, transcript), settings.jev_model)
    headers = {"Authorization": f"Bearer {settings.jev_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for attempt in range(3):
                response = await client.post(settings.jev_api_url, json=body, headers=headers)
                # 429 = rate limited, 529 = overloaded: back off and retry.
                if response.status_code in (429, 529) and attempt < 2:
                    await asyncio.sleep(0.5 * 2**attempt)
                    continue
                break
        if response.status_code != 200:
            return (
                ClassificationResult.unavailable(
                    f"Jev HTTP {response.status_code}: {response.text[:300]}"
                ),
                None,
            )
        raw = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ClassificationResult.unavailable(f"Jev request failed: {exc}"), None

    return normalize_response(raw), raw
