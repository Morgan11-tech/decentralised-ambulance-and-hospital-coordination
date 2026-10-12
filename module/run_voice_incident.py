"""
run_voice_incident.py — Simulate how a voice-agent incident is resolved.

Takes one incident recorded by the conversational agent (from MongoDB, or a JSON
file), gives it coordinates and runs the model on that incident alone in the
centralized and/or decentralized condition, then reports what happened to it
(which unit, response time, hospital, offload).

The coordination mode is the experimental condition, not a property of the
incident, so by default the incident is simulated under BOTH modes.

Usage:
  python run_voice_incident.py                        # latest incident in MongoDB, both modes
  python run_voice_incident.py --id INC-DD9ADB398988  # a specific one
  python run_voice_incident.py --file ../conversational-agent/examples/sample_incident.json
  python run_voice_incident.py --mode decentralized
  python run_voice_incident.py --latlon 52.2393 6.8555  # override the location lookup
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.chdir(HERE)  # model/config use paths relative to module/

import config  # noqa: E402
from incidents import to_operational_code  # noqa: E402
from model import EmergencyModel  # noqa: E402

SCHEMA_PATH = HERE.parent / "conversational-agent" / "schemas" / "incident.schema.json"
MAX_TICKS = 24 * 60

# Free-text location -> (lat, lon). The voice agent stores only what the caller
# said, so these tables map known places to coordinates. Tiers are checked from
# most to least specific, so "Vrijhof, University of Twente" resolves to the
# Vrijhof, not the campus centre. Names match whole words only.
# [ASSUMPTION] approximate coordinates; extend as callers name new places.
CAMPUS_BUILDINGS = {
    "vrijhof": (52.2446, 6.8527),
    "horst": (52.2381, 6.8566),
    "ravelijn": (52.2394, 6.8554),
    "zilverling": (52.2393, 6.8572),
    "waaier": (52.2386, 6.8560),
    "spiegel": (52.2410, 6.8517),
    "bastille": (52.2422, 6.8519),
    "sportcentrum": (52.2457, 6.8475),
    # Hospitals
    "mst": (52.211, 6.881),
    "medisch spectrum": (52.211, 6.881),
    "zgt": (52.345, 6.672),
}
CAMPUS = {
    "university of twente": (52.2393, 6.8555),
    "utwente": (52.2393, 6.8555),
    "ut campus": (52.2393, 6.8555),
    "drienerlo": (52.2420, 6.8520),
}
TOWNS = {
    "enschede": (52.221, 6.893),
    "hengelo": (52.265, 6.793),
    "almelo": (52.357, 6.662),
    "oldenzaal": (52.313, 6.928),
    "borne": (52.300, 6.752),
    "haaksbergen": (52.159, 6.742),
    "goor": (52.231, 6.583),
    "markelo": (52.244, 6.513),
    "nijverdal": (52.363, 6.462),
    "rijssen": (52.307, 6.519),
    "wierden": (52.359, 6.594),
    "delden": (52.261, 6.711),
    "losser": (52.261, 7.005),
    "glanerbrug": (52.214, 6.975),
    "tubbergen": (52.408, 6.777),
    "ootmarsum": (52.408, 6.901),
    "vroomshoop": (52.448, 6.567),
}
PLACE_TIERS = (CAMPUS_BUILDINGS, CAMPUS, TOWNS)


# --- loading ---------------------------------------------------------------------


def from_mongo(uri: str, incident_id: str | None) -> dict:
    from pymongo import MongoClient

    collection = MongoClient(uri, serverSelectionTimeoutMS=3000)["emergency_voice_agent"]["incidents"]
    if incident_id:
        doc = collection.find_one({"_id": incident_id}, {"incident": 1})
        if doc is None:
            sys.exit(f"No incident {incident_id} in MongoDB.")
    else:
        doc = collection.find_one({}, {"incident": 1}, sort=[("created_at", -1)])
        if doc is None:
            sys.exit("MongoDB has no incidents yet. Record one with the voice agent first.")
    return doc["incident"]


def from_file(path: str, incident_id: str | None) -> dict:
    with open(path) as f:
        raw = json.load(f)
    records = raw if isinstance(raw, list) else [raw]
    if incident_id:
        records = [r for r in records if r.get("incident_id") == incident_id]
        if not records:
            sys.exit(f"No incident {incident_id} in {path}.")
    return records[-1]


def validate(record: dict) -> None:
    try:
        from jsonschema import validate as js_validate
    except ImportError:
        print("[warn] jsonschema not installed; skipping schema validation")
        return
    with open(SCHEMA_PATH) as f:
        js_validate(instance=record, schema=json.load(f))


# --- preparing the voice incident ---------------------------------------------------


def geocode(raw_text: str | None) -> tuple[float, float] | None:
    text = (raw_text or "").lower()
    for places in PLACE_TIERS:
        for name, latlon in places.items():
            if re.search(rf"\b{re.escape(name)}\b", text):
                return latlon
    return None


def prepare(record: dict, latlon: tuple[float, float] | None) -> dict:
    record = copy.deepcopy(record)
    loc = record["location"]
    if latlon:
        loc["latitude"], loc["longitude"] = latlon
    elif loc.get("latitude") is None or loc.get("longitude") is None:
        found = geocode(loc.get("raw_text"))
        if found is None:
            sys.exit(
                f"Cannot place location {loc.get('raw_text')!r} on the map.\n"
                "Pass --latlon LAT LON, or add the place to the tables in run_voice_incident.py."
            )
        loc["latitude"], loc["longitude"] = found
        print(f"Location {loc['raw_text']!r} -> ({found[0]}, {found[1]})")
    return record


# --- running -----------------------------------------------------------------------


def _post_name(pos) -> str:
    return min(config.POSTS_XY, key=lambda n: math.hypot(config.POSTS_XY[n][0] - pos[0],
                                                         config.POSTS_XY[n][1] - pos[1]))


def run(mode: str, incident: dict, seed: int) -> dict:
    # The model only loads incidents from a file, so hand it a throwaway one.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "incident.json"
        path.write_text(json.dumps([incident]))
        model = EmergencyModel(seed=seed, incident_file=str(path), mode=mode)
    if not model.incidents:
        sys.exit("The incident was not loaded by the model (see warnings above).")
    tracked = model.incidents[0]

    unit = post = hospital = None
    while model.clock < MAX_TICKS and not model.completed:
        model.step()
        for amb in model.ambulances:
            if amb.current_incident is tracked:
                if unit is None:
                    unit, post = amb.unique_id, _post_name(amb.home_pos)
                if amb.dest_hospital is not None:
                    hospital = amb.dest_hospital.name

    return {
        "mode": mode,
        "code": tracked.code,
        "assigned_after": None if tracked.assigned_tick is None else tracked.assigned_tick - tracked.created_tick,
        "response": tracked.response_min,
        "unit": f"amb#{unit} ({post})" if unit is not None else "none",
        "transport": hospital or ("no transport" if tracked.closed_tick is not None else "-"),
        "offload": tracked.offload_min,
        "closed_after": None if tracked.closed_tick is None else tracked.closed_tick - tracked.created_tick,
        "metrics": model.metrics,
    }


def _fmt(v, unit=""):
    if v is None:
        return "-"
    if isinstance(v, float):
        return "-" if math.isnan(v) else f"{v:.1f}{unit}"
    return f"{v}{unit}"


def report(voice: dict, results: list[dict]) -> None:
    patients = voice["patients"]
    print()
    print(f"Incident {voice['incident_id']}: {voice['incident']['description']}")
    print(f"  {voice['incident']['type']}, {voice['incident']['severity']}, "
          f"{patients['count'] or 1} patient(s), at {voice['location']['raw_text']!r}")
    if (patients["count"] or 1) > 1:
        print("  [note] the model sends ONE ambulance per incident; extra patients are not simulated yet")

    rows = [
        ("Operational code", lambda r: r["code"]),
        ("Unit assigned after", lambda r: _fmt(r["assigned_after"], " min")),
        ("Response time", lambda r: _fmt(r["response"], " min")),
        ("Ambulance", lambda r: r["unit"]),
        ("Hospital", lambda r: r["transport"]),
        ("Offload delay", lambda r: _fmt(r["offload"], " min")),
        ("Closed after", lambda r: _fmt(r["closed_after"], " min")),
        ("Messages sent", lambda r: _fmt(r["metrics"]["msgs_total"])),
    ]
    width = max(len(label) for label, _ in rows) + 2
    print()
    print("".ljust(width) + "".join(r["mode"].ljust(20) for r in results))
    for label, get in rows:
        print(label.ljust(width) + "".join(str(get(r)).ljust(20) for r in results))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--file", help="read the incident from a JSON file instead of MongoDB")
    src.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    p.add_argument("--id", help="incident_id to simulate (default: the most recent)")
    p.add_argument("--mode", choices=["centralized", "decentralized", "both"], default="both")
    p.add_argument("--latlon", nargs=2, type=float, metavar=("LAT", "LON"),
                   help="coordinates for the incident (skips the location lookup)")
    p.add_argument("--seed", type=int, default=config.SEED)
    args = p.parse_args()

    record = from_file(args.file, args.id) if args.file else from_mongo(args.mongo_uri, args.id)
    validate(record)
    voice = prepare(record, tuple(args.latlon) if args.latlon else None)

    code = to_operational_code(voice["incident"]["severity"], voice["patients"]["primary_patient"]["breathing"])
    if code == "B":
        sys.exit("Severity is non_urgent (code B): the emergency model does not simulate planned transport.")

    modes = ["centralized", "decentralized"] if args.mode == "both" else [args.mode]
    report(voice, [run(m, voice, args.seed) for m in modes])


if __name__ == "__main__":
    main()
