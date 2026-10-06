"""
generate_incidents.py — Synthetic incident stream for experiments and demos.

Spreads incidents across Twente, weighted toward the cities, and writes a
schema-valid incident.json. Deterministic given a seed, so experiments replay.

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

# Operational code -> schema fields (reverse of the loader's mapping).
_CODE_TO_SCHEMA = {
    "A0": ("critical", "cardiac_or_circulatory", {"consciousness": "unconscious",
                                                  "breathing": "not_breathing", "bleeding": "none"}),
    "A1": ("critical", "cardiac_or_circulatory", {"consciousness": "conscious",
                                                  "breathing": "normal", "bleeding": "none"}),
    "A2": ("urgent", "trauma", {"consciousness": "conscious",
                                "breathing": "normal", "bleeding": "present"}),
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
        severity, itype, patient = _CODE_TO_SCHEMA[code]
        lat, lon = _sample_pos(rng)
        records.append({
            "schema_version": "1.0",
            "incident_id": f"gen-{i:03d}",
            "session_id": f"sess-{i:03d}",
            "created_at": (base + timedelta(minutes=off)).isoformat().replace("+00:00", "Z"),
            "location": {"raw_text": None, "latitude": round(lat, 5), "longitude": round(lon, 5)},
            "incident_description": f"synthetic {code} incident",
            "incident_type": itype,
            "severity": severity,
            "patient": patient,
            "number_of_patients": 1,
            "classification": {"classifier": "synthetic"},
            "source": "synthetic_generator",
            "status": "ready_for_dispatch",
        })

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