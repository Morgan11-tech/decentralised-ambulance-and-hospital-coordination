"""
incidents.py — Load incident.json into simulation incidents.

Records follow the canonical contract (schema 1.0):
conversational-agent/schemas/incident.schema.json, documented in
conversational-agent/docs/incident-schema.md.

Does three jobs:
  1. Maps the schema's coarse severity to the operational Dutch codes A0/A1/A2/B,
     using the breathing signal so an arrest becomes A0 (resuscitation).
  2. Projects real lat/lon onto the local km grid (via config.latlon_to_xy).
  3. Pre-samples on-scene time and transport outcome with a seeded RNG, so every
     run (condition A or B) replays the identical incident stream.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime

import config


def to_operational_code(severity: str, breathing: str) -> str:
    """Schema severity (+ breathing) -> A0 / A1 / A2 / B.

    A0 = resuscitation: 'critical' AND not breathing (arrest).
    A1 = other life-threatening 'critical'.  A2 = 'urgent'.  B = 'non_urgent'.
    'uncertain' -> A1 (fail safe: dispatch as if life-threatening).
    """
    if severity == "critical":
        return "A0" if breathing == "not_breathing" else "A1"
    if severity == "urgent":
        return "A2"
    if severity == "non_urgent":
        return "B"
    return "A1"


@dataclass
class Incident:
    incident_id: str
    session_id: str | None
    created_tick: int                 # minutes from the first incident
    pos: tuple[float, float]          # (x_km, y_km) on the grid
    code: str                         # A0 / A1 / A2 / B
    incident_type: str
    on_scene_min: float               # pre-sampled treatment time
    transport_needed: bool            # pre-sampled (A0: ROSC -> transport)
    los_min: float = 0.0              # pre-sampled hospital length of stay (if admitted)
    offload_min: float = 0.0          # filled at runtime if the ED made the unit wait
    immediate_dispatch: bool = False  # A0: skip bidding, send nearest now
    n_patients: int = 1
    # lifecycle timestamps (ticks), filled during the run
    answered_tick: int | None = None   # call processing started (A: an operator picked it up)
    assigned_tick: int | None = None
    on_scene_tick: int | None = None
    closed_tick: int | None = None

    @property
    def response_min(self):
        """On-scene arrival time minus creation time, in minutes (None if not reached)."""
        if self.on_scene_tick is None:
            return None
        return self.on_scene_tick - self.created_tick


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load_incidents(path: str, seed: int = config.SEED, include_planned: bool = False):
    """Load incident.json and return Incident objects sorted by created_tick."""
    with open(path) as f:
        raw = json.load(f)
    return incidents_from_records(raw, seed=seed, include_planned=include_planned)


def incidents_from_records(raw, seed: int = config.SEED, include_planned: bool = False, t0=None):
    """Turn schema records (one dict or a list) into Incident objects sorted by created_tick.

    seed -> reproducible on-scene times / transport outcomes (same stream for A and B).
    include_planned=False drops B (planned transport); it is not an emergency.
    t0 = the moment that becomes tick 0 (a datetime). None = the earliest call, which suits a
    single voice incident; generated streams pass their start time, so the clock covers the whole
    generated period and is not shifted by when the first call happens to fall.
    """
    rng = random.Random(seed)
    records = raw if isinstance(raw, list) else [raw]   # accept one or many

    times = [_parse_dt(r["created_at"]) for r in records if r.get("created_at")]
    if t0 is None:
        t0 = min(times) if times else None              # earliest call = tick 0

    incidents, skipped = [], 0
    for i, r in enumerate(records):
        loc = r.get("location") or {}
        lat, lon = loc.get("latitude"), loc.get("longitude")
        if lat is None or lon is None:
            skipped += 1
            continue                                    # the sim needs coordinates
        x, y = config.latlon_to_xy(lat, lon)
        if not (0 <= x <= config.SPACE_WIDTH_KM and 0 <= y <= config.SPACE_HEIGHT_KM):
            print(f"[warn] incident {r.get('incident_id', i)} at ({x:.1f},{y:.1f}) km is outside the map")

        details = r["incident"]
        patients = r["patients"]
        breathing = patients["primary_patient"]["breathing"]
        code = to_operational_code(details["severity"], breathing)
        if code == "B" and not include_planned:
            continue

        prof = config.SEVERITY_PROFILE.get(code)
        if prof:
            on_scene = max(1.0, rng.gauss(prof["on_scene_mean_min"], prof["on_scene_sd_min"]))
            transport = rng.random() < prof["transport_prob"]
            immediate = prof.get("immediate_dispatch", False)
            los = max(config.HOSPITAL_LOS_FLOOR_MIN,
                      rng.gauss(config.HOSPITAL_LOS_MEAN_MIN, config.HOSPITAL_LOS_MEAN_MIN * 0.3))
        else:  # B, only reached when include_planned=True
            on_scene, transport, immediate, los = 10.0, True, False, config.HOSPITAL_LOS_MEAN_MIN

        if t0 is not None and r.get("created_at"):
            tick = int(round((_parse_dt(r["created_at"]) - t0).total_seconds() / 60.0))
        else:
            tick = i

        incidents.append(Incident(
            incident_id=str(r.get("incident_id", f"inc-{i}")),
            session_id=r.get("session_id"),
            created_tick=tick,
            pos=(x, y),
            code=code,
            incident_type=details["type"],
            on_scene_min=round(on_scene, 1),
            transport_needed=transport,
            immediate_dispatch=immediate,
            los_min=round(los, 1),
            n_patients=patients["count"] or 1,   # null = unknown -> 1
        ))

    incidents.sort(key=lambda inc: inc.created_tick)
    if skipped:
        print(f"[warn] skipped {skipped} incident(s) with no coordinates")
    return incidents