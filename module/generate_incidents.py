"""
generate_incidents.py — Synthetic incident stream for experiments and demos.

Spreads incidents across Twente, weighted toward the cities, and writes an
incident.json valid against conversational-agent/schemas/incident.schema.json.
Deterministic given a seed, so experiments replay.

Usage:  python generate_incidents.py --n 18 --minutes 180 --out data/incident.json
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone

import config

# Urban centres (lat, lon) with relative weights; rest is rural scatter.
# a stand in for the real population distribution, so incidents cluster in the cities.
_CENTRES = [
    ((52.221, 6.893), 5),   # Enschede
    ((52.265, 6.793), 3),   # Hengelo
    ((52.357, 6.662), 2),   # Almelo
    ((52.313, 6.928), 1),   # Oldenzaal
]

# Operational code -> schema-valid clinical profiles (reverse of the loader's mapping).
# Combinations follow Jev's criteria (conversational-agent/backend/services/jev_service.py):
#   critical = unconscious, not/abnormally breathing, or severe bleeding
#   urgent   = conscious and breathing normally, but needs help soon
# so a synthetic incident carries the label the voice agent's classifier would give it.
# Each profile: (type, severity, description, mechanism, consciousness, breathing,
#                severe_bleeding, symptoms)
_CODE_TO_PROFILES = {
    # A0: arrest -> critical AND not breathing (the loader's only A0 route).
    "A0": [
        ("cardiac_or_circulatory", "critical", "Person collapsed and is not breathing.", None,
         "unconscious", "not_breathing", "absent", ["sudden collapse"]),
        ("respiratory", "critical", "Person choked while eating and stopped breathing.", "choking",
         "unconscious", "not_breathing", "absent", ["choking"]),
    ],
    # A1: life-threatening but breathing -> critical via another sign.
    "A1": [
        ("cardiac_or_circulatory", "critical", "Person with chest pain is struggling to breathe.", None,
         "conscious", "abnormal", "absent", ["chest pain", "pale and sweating"]),
        ("respiratory", "critical", "Severe asthma attack, person is gasping for air.", None,
         "conscious", "abnormal", "absent", ["shortness of breath", "wheezing"]),
        ("neurological", "critical", "Person suddenly collapsed and does not respond.", None,
         "unconscious", "normal", "absent", ["face drooping", "unresponsive"]),
        ("trauma", "critical", "Cyclist hit by a car, heavy bleeding from the leg.", "car collision",
         "conscious", "normal", "present", ["leg injury"]),
    ],
    # A2: urgent -> conscious, breathing normally, no severe bleeding.
    "A2": [
        ("trauma", "urgent", "Person fell off a bicycle and hit their head.", "bicycle fall",
         "conscious", "normal", "absent", ["head injury", "bleeding from the head"]),
        ("trauma", "urgent", "Person fell down the stairs and hurt their hip.", "fall",
         "conscious", "normal", "absent", ["hip pain", "cannot stand"]),
        ("cardiac_or_circulatory", "urgent", "Person has chest pain but is breathing normally.", None,
         "conscious", "normal", "absent", ["chest pain"]),
        ("bleeding", "urgent", "Deep cut on the hand that keeps bleeding.", "kitchen knife",
         "conscious", "normal", "absent", ["bleeding hand wound"]),
    ],
}


def _concern(observation, yes, no):
    """Concern label from an observation, per Jev's yes/no criteria; unknown -> uncertain."""
    return "yes" if observation in yes else "no" if observation in no else "uncertain"


def _label(value):
    return {"value": value, "confidence": None}   # synthetic: no classifier confidence


def _record(i, created_at, lat, lon, profile):
    itype, severity, description, mechanism, consciousness, breathing, bleeding, symptoms = profile
    return {
        "schema_version": "1.0",
        "incident_id": f"gen-{i:03d}",
        "session_id": None,                       # no voice session for synthetic incidents
        "created_at": created_at,
        "source": "synthetic_generator",
        "location": {"raw_text": None, "latitude": round(lat, 5), "longitude": round(lon, 5)},
        "incident": {"description": description, "mechanism": mechanism,
                     "type": itype, "severity": severity},
        "patients": {
            "count": 1,
            "primary_patient": {"consciousness": consciousness, "breathing": breathing,
                                "severe_bleeding": bleeding, "symptoms": list(symptoms)},
        },
        "scene": {
            "entrapment": "not_relevant",
            "immediate_danger": "unknown" if mechanism == "car collision" else "not_relevant",
        },
        "classification": {
            "incident_type": _label(itype),
            "severity": _label(severity),
            "consciousness_concern": _label(_concern(consciousness, {"unconscious"}, {"conscious"})),
            "breathing_concern": _label(_concern(breathing, {"abnormal", "not_breathing"}, {"normal"})),
        },
        "status": "ready_for_dispatch",
    }


def _sample_pos(rng):
    """Return a jittered (lat, lon): usually near a city, sometimes rural."""
    if rng.random() < 0.75:   # urban: near a weighted centre
        (lat, lon), _ = rng.choices(_CENTRES, weights=[w for _, w in _CENTRES])[0]
        x, y = config.latlon_to_xy(lat, lon)
        x += rng.gauss(0, 2.5)   # ~2.5 km spread, so NOT exactly on a post
        y += rng.gauss(0, 2.5)
    else:                     # rural: uniform across the region
        x = rng.uniform(3, config.SPACE_WIDTH_KM - 3)
        y = rng.uniform(3, config.SPACE_HEIGHT_KM - 3)
    x = min(max(x, 0.5), config.SPACE_WIDTH_KM - 0.5)
    y = min(max(y, 0.5), config.SPACE_HEIGHT_KM - 0.5)
    return config.xy_to_latlon(x, y)


def generate(n=18, minutes=180, seed=config.SEED, out="data/incident.json"):
    rng = random.Random(seed)
    codes = list(config.SEVERITY_MIX.keys())          # A0, A1, A2
    weights = list(config.SEVERITY_MIX.values())
    base = datetime(2026, 2, 1, 8, 0, tzinfo=timezone.utc)

    offsets = sorted(rng.uniform(0, minutes) for _ in range(n))
    records = []
    for i, off in enumerate(offsets):
        code = rng.choices(codes, weights=weights)[0]
        profile = rng.choice(_CODE_TO_PROFILES[code])
        lat, lon = _sample_pos(rng)
        created_at = (base + timedelta(minutes=off)).isoformat().replace("+00:00", "Z")
        records.append(_record(i, created_at, lat, lon, profile))

    import os
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(records, f, indent=2)
    print(f"wrote {len(records)} incidents to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=18)
    ap.add_argument("--minutes", type=int, default=180)
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--out", default="data/incident.json")
    a = ap.parse_args()
    generate(a.n, a.minutes, a.seed, a.out)