"""
run_experiments.py — Headless experiment suite E1-E6 (centralized vs decentralized).

Writes one row per (experiment, mode, swept value, seed) to results/experiments.csv,
plus results/e4_timeline.csv (per-call response times for the outage experiment).
Then run `python experiments/analyze.py` for figures and tables.

Modes: centralized (dispatcher with N_DISPATCH_OPERATORS call-takers, most urgent first) and
decentralized (Contract Net, urgency-ordered). Both serve the most urgent calls first.

  E1  baseline          normal demand, perfect comms (calibration check)
  E2  demand            load x {1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5}
  E3  comms             loss_prob {0..0.5} and delay_ticks {0,1,2,3,5}, at normal AND high load
  E4  dispatcher outage outage_len {0,15,30,60,90,120} min, at high load. ONLY experiment that
                        also runs the hybrid (centralized, Contract Net while the dispatcher is down)
  E4-switch             hybrid's SWITCHOVER_DELAY_MIN {0..60} at a 60-min outage, high load;
                        centralized and decentralized run alongside as references
  E5  bidding window    BID_WINDOW_TICKS {0,1,2,3} (decentralized), normal load; centralized
                        runs alongside as the reference
  E6  operators         N_DISPATCH_OPERATORS {1,2,3,5, unlimited}, at normal AND high load
                        (only the centralized mode uses operators; decentralized is the reference)

Every mode pays config.DISPATCH_HANDLING_MIN of call processing; in centralized it needs a free
operator, so calls can queue for one. These results supersede all earlier ones.

"High load" for E3/E4/E6 is chosen from the E2 results with a rule fixed in advance:
the highest E2 load at which the centralized baseline still finishes >= 95% of calls
(stressed, but not collapsed). Comms effects are invisible with lots of spare
capacity and meaningless once everything is queued anyway.

Usage (from module/):  python experiments/run_experiments.py [--seeds 30] [--high-load X]
                       python experiments/run_experiments.py --only-e4
  --only-e4 re-runs E4 and E4-switch at the stored high load and replaces just those rows (and
  e4_timeline.csv); the other experiments are untouched (A and B runs are deterministic per seed).
"""

import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)  # data/ and results/ paths are relative to the module root
import statistics as st

import config
import experiment_core as ec

MODES = ("centralized", "decentralized")
E4_MODES = MODES + ("hybrid",)        # the hybrid only matters when the dispatcher can fail
SEED_BASE = 101                       # calibration used seeds 1-10; these are fresh

E2_LOADS = [1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4, 5]   # brief's {1,1.5,2,3,4,5} + points near the knee
E3_LOSS = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
E3_DELAY = [0, 1, 2, 3, 5]
E4_OUTAGE = [0, 15, 30, 60, 90, 120]
E5_WINDOWS = [0, 1, 2, 3]
UNLIMITED_OPERATORS = 100             # far more than ever busy at once = the old unlimited model
E6_OPERATORS = [1, 2, 3, 5, UNLIMITED_OPERATORS]
OUTAGE_START = ec.WARMUP_MIN + 600    # 10 h into the measured day
OUTAGE_AFTER = 60                     # also measure calls created up to 60 min after it ends
SWITCH_DELAYS = [0, 2, 5, 10, 20, 30, 50, 60]   # [ASSUMPTION] minutes to notice the outage; 50 ~ 2019 GRIP-2 time [VRT-2019], 60 = never in time
SWITCH_OUTAGE = 60                    # outage length for the switchover sweep

OUT_CSV = "results/experiments.csv"
OUT_TIMELINE = "results/e4_timeline.csv"
OUT_HIGH = "results/high_load.txt"


def tasks_for(exp, var, values, seeds, modes=MODES, **fixed):
    for v in values:
        for mode in modes:
            for s in seeds:
                t = {"experiment": exp, "swept_var": var, "swept_value": v,
                     "mode": mode, "seed": s, "load": 1.0,
                     "n_ambulances": config.N_AMBULANCES,
                     "n_operators": config.N_DISPATCH_OPERATORS,
                     "loss_prob": 0.0, "delay_ticks": 0, "outage_len": 0, **fixed}
                if var != "none":
                    t[var] = v
                yield t


def e5_tasks(seeds):
    """Decentralized bidding window swept; centralized once per seed as the reference."""
    out = []
    for t in tasks_for("E5", "bid_window", E5_WINDOWS, seeds, modes=("decentralized",)):
        t["overrides"] = {"BID_WINDOW_TICKS": t["swept_value"]}
        out.append(t)
    out += list(tasks_for("E5", "bid_window", [None], seeds, modes=("centralized",)))
    return out


def e4_tasks(seeds, high):
    """E4: outage sweep for all three modes on identical incidents per seed. E4-switch: the
    hybrid's switchover delay swept at one outage length, A and B once per seed as references."""
    out = []
    for t in tasks_for("E4", "outage_len", E4_OUTAGE, seeds, modes=E4_MODES, load=high,
                       outage_start=OUTAGE_START, timeline=True):
        t["event_window"] = (OUTAGE_START, OUTAGE_START + t["outage_len"] + OUTAGE_AFTER)
        out.append(t)
    sw = list(tasks_for("E4-switch", "switchover_delay", SWITCH_DELAYS, seeds, modes=("hybrid",)))
    for t in sw:
        t["overrides"] = {"SWITCHOVER_DELAY_MIN": t["swept_value"]}
    sw += list(tasks_for("E4-switch", "switchover_delay", [None], seeds, modes=MODES))
    for t in sw:
        t.update(load=high, outage_start=OUTAGE_START, outage_len=SWITCH_OUTAGE,
                 event_window=(OUTAGE_START, OUTAGE_START + SWITCH_OUTAGE + OUTAGE_AFTER))
        t.pop("switchover_delay", None)
    return out + sw


def split_timeline(rows):
    timeline = []
    for r in rows:
        tl = r.pop("_timeline", None)
        r.pop("event_window", None)
        if tl:
            timeline += [{"mode": r["mode"], "seed": r["seed"], "load": r["load"],
                          "outage_len": r["outage_len"],
                          "created_tick": c, "code": code, "response_min": resp}
                         for c, code, resp in tl]
    return timeline


def write_csv(path, rows):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def only_e4(seeds):
    """Re-run E4 + E4-switch and splice them into the existing results."""
    high = float(open(OUT_HIGH).read().strip())
    tasks = e4_tasks(seeds, high)
    print(f"E4 + E4-switch at {high}x: {len(tasks)} runs")
    new = ec.run_many(tasks)
    timeline = split_timeline(new)
    with open(OUT_CSV, newline="") as fh:
        kept = [r for r in csv.DictReader(fh) if r["experiment"] not in ("E4", "E4-switch")]
    write_csv(OUT_CSV, kept + new)
    write_csv(OUT_TIMELINE, timeline)
    print(f"replaced E4 rows: {len(kept)} kept + {len(new)} new in {OUT_CSV}; "
          f"{len(timeline)} rows to {OUT_TIMELINE}")


def pick_high_load(rows):
    ok = []
    for load in E2_LOADS:
        rs = [r for r in rows if r["experiment"] == "E2" and r["mode"] == "centralized"
              and r["swept_value"] == load]
        if st.mean(r["win_unserved_pct"] for r in rs) < 5.0:
            ok.append(load)
    return max(ok) if ok else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--high-load", type=float, default=None,
                    help="override the rule that picks the E3/E4/E6 load from E2")
    ap.add_argument("--only-e4", action="store_true",
                    help="re-run only E4 + E4-switch and splice them into the existing CSV")
    a = ap.parse_args()
    seeds = list(range(SEED_BASE, SEED_BASE + a.seeds))
    if a.only_e4:
        return only_e4(seeds)

    first = list(tasks_for("E1", "none", [0], seeds)) + list(tasks_for("E2", "load", E2_LOADS, seeds))
    print(f"E1-E2: {len(first)} runs")
    rows = ec.run_many(first)

    high = a.high_load or pick_high_load(rows)
    os.makedirs("results", exist_ok=True)
    with open(OUT_HIGH, "w") as fh:
        fh.write(f"{high}\n")
    print(f"high load for E3/E4/E6 = {high}x normal")

    second = []
    for load in (1.0, high):
        second += list(tasks_for("E3-loss", "loss_prob", E3_LOSS, seeds, load=load))
        second += list(tasks_for("E3-delay", "delay_ticks", E3_DELAY, seeds, load=load))
        second += list(tasks_for("E6", "n_operators", E6_OPERATORS, seeds, load=load))
    second += e4_tasks(seeds, high)
    second += e5_tasks(seeds)
    print(f"E3-E6: {len(second)} runs")
    rows += ec.run_many(second)

    timeline = split_timeline(rows)
    write_csv(OUT_CSV, rows)
    write_csv(OUT_TIMELINE, timeline)
    print(f"wrote {len(rows)} rows to {OUT_CSV} and {len(timeline)} rows to {OUT_TIMELINE}")


if __name__ == "__main__":
    main()
