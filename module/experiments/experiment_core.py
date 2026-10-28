"""
experiment_core.py — Headless run harness shared by calibrate.py and run_experiments.py.

One "run" = one (setting, seed): generate an incident stream, run the model on it
without the Solara UI, and return window_summary() metrics.

Run timeline (minutes):
  [0, WARMUP)                    incidents arrive, but are NOT measured (hospitals fill up)
  [WARMUP, WARMUP + WINDOW)      measured incidents
  [.., + DRAIN)                  no new incidents; units finish work in progress
A call still waiting at the end counts with the time it had waited (a lower bound).

Controlled comparison: for a given (setting, seed) the incident records AND the model
seed are identical in both modes, so the only difference is the dispatch strategy.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)  # data/ and results/ paths are relative to the module root

import config
import generate_incidents
import metrics
from model import EmergencyModel

WARMUP_MIN = 240      # [ASSUMPTION] > one mean hospital stay (config.HOSPITAL_LOS_MEAN_MIN), so EDs reach steady occupancy
WINDOW_MIN = 1440     # one simulated day of measured calls per run
DRAIN_MIN = 120       # let in-progress calls finish; longer backlog = unserved

# Normal demand for Twente [Ambulance Oost via Sectorkompas; Tweede Kamer Aanhangsel 2025-2026, 747]:
# 23,238 A1 (incl. A0) dispatches in 2024 -> 2.65 urgent calls/hour. The model also simulates
# A2 calls; the generator draws codes in the national mix (A0+A1 = 62.4% of A0..A2) [RIVM/VZinfo],
# so the total emergency rate is 2.65 / 0.624 = 4.25 calls/hour.
URGENT_PER_YEAR_TWENTE = 23_238
URGENT_RATE_PER_HR = URGENT_PER_YEAR_TWENTE / (365 * 24)
URGENT_SHARE_OF_EMERGENCY = config.SEVERITY_MIX["A0"] + config.SEVERITY_MIX["A1"]
NORMAL_RATE_PER_HR = URGENT_RATE_PER_HR / URGENT_SHARE_OF_EMERGENCY


@contextmanager
def config_overrides(**kw):
    """Temporarily set config values (e.g. EFFECTIVE_SPEED_KMH, HOSPITAL_LOS_MEAN_MIN).

    capacity={"MST Enschede": 8, ...} patches the hospital capacities the model reads.
    """
    saved = {}
    caps = kw.pop("capacity", None)
    for k, v in kw.items():
        saved[k] = getattr(config, k)
        setattr(config, k, v)
    if caps:
        saved["HOSPITALS_XY"] = config.HOSPITALS_XY
        config.HOSPITALS_XY = {n: {**h, "capacity": caps.get(n, h["capacity"])}
                               for n, h in config.HOSPITALS_XY.items()}
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


def make_records(load=1.0, seed=1, minutes=WARMUP_MIN + WINDOW_MIN):
    n = round(NORMAL_RATE_PER_HR * load * minutes / 60.0)
    return generate_incidents.generate_records(n=n, minutes=minutes, seed=seed)


def run_one(task: dict) -> dict:
    """Run one setting/seed. task keys: mode, seed, load, n_ambulances, n_operators, loss_prob,
    delay_ticks, outage_start, outage_len, overrides (dict), timeline (bool), + any labels."""
    overrides = dict(task.get("overrides") or {})
    with config_overrides(**overrides):
        records = make_records(task.get("load", 1.0), task["seed"])
        m = EmergencyModel(seed=task["seed"], mode=task["mode"],
                           n_ambulances=task.get("n_ambulances"),
                           loss_prob=task.get("loss_prob", 0.0),
                           delay_ticks=task.get("delay_ticks", 0),
                           outage_start=task.get("outage_start", 0),
                           outage_len=task.get("outage_len", 0),
                           incidents=records, n_operators=task.get("n_operators"),
                           incidents_t0=generate_incidents.BASE_TIME)   # minute 0 = start of the stream
        end = WARMUP_MIN + WINDOW_MIN + DRAIN_MIN
        while m.clock < end:
            m.step()
        row = metrics.window_summary(m, WARMUP_MIN, WARMUP_MIN + WINDOW_MIN)
        if task.get("event_window"):          # extra metrics for calls created in a sub-window
            a, b = task["event_window"]
            ev = metrics.window_summary(m, a, b)
            row.update({f"ev_{k}": ev[k] for k in ("urg_resp_mean", "urg_resp_p95",
                                                  "urg_within15_pct", "urg_n")})
        if task.get("timeline"):
            row["_timeline"] = [
                (i.created_tick, i.code,
                 i.response_min if i.response_min is not None else m.clock - i.created_tick)
                for i in m.incidents]
    labels = {k: v for k, v in task.items() if k not in ("overrides", "timeline")}
    labels.update({f"cfg_{k}": v for k, v in overrides.items() if k != "capacity"})
    if "capacity" in overrides:
        labels["cfg_capacity"] = "/".join(str(v) for v in overrides["capacity"].values())
    row.pop("mode", None)
    return {**labels, **row}


def run_many(tasks, workers=None):
    """Run tasks in parallel processes; results come back in task order."""
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(run_one, tasks, chunksize=1))
