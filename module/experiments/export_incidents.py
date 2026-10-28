"""
export_incidents.py — The incidents every experiment actually ran on, in readable form.

Rebuilds each (load, seed) incident stream exactly as experiment_core.run_one does (same generator,
same seed, same loader), so the numbers are the model's inputs, not a re-draw.

  python experiments/export_incidents.py
    -> results/incidents_report.md          per-experiment arrival rates, mixes, hourly counts
    -> results/incidents/incidents.csv      one row per incident per (load, seed)

An incident stream depends only on (load, seed), never on the mode or the swept setting, so all
modes in a sweep, and all experiments at the same load, share identical incidents.
"""

import csv
import os
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

import config
import experiment_core as ec
import generate_incidents
import metrics
import run_experiments as rx
from incidents import incidents_from_records

OUT_MD = "results/incidents_report.md"
OUT_DIR = "results/incidents"
OUT_CSV = os.path.join(OUT_DIR, "incidents.csv")
W0, W1 = ec.WARMUP_MIN, ec.WARMUP_MIN + ec.WINDOW_MIN       # measured window, in model minutes
CODES = ("A0", "A1", "A2")


def experiment_loads(high):
    """Which demand levels each experiment ran at (mirrors run_experiments.main)."""
    return {
        "E1 baseline": [1.0],
        "E2 demand sweep": rx.E2_LOADS,
        "E3 message loss / delay": [1.0, high],
        "E4 dispatcher outage": [high],
        "E4-switch switchover delay": [high],
        "E5 bidding window": [1.0],
        "E6 operators": [1.0, high],
    }


def stream(load, seed):
    """(records, Incident objects) exactly as the model sees them."""
    recs = ec.make_records(load, seed)
    return recs, incidents_from_records(recs, seed=seed, t0=generate_incidents.BASE_TIME)


def summ(vals, d=1):
    """'mean (min–max)' over seeds."""
    return f"{st.mean(vals):.{d}f} ({min(vals):.{d}f}–{max(vals):.{d}f})"


def load_stats(load, seeds):
    per = []
    for s in seeds:
        _, incs = stream(load, s)
        win = [i for i in incs if W0 <= i.created_tick < W1]
        hrs = (W1 - W0) / 60
        hourly = [sum(1 for i in win if W0 + 60 * h <= i.created_tick < W0 + 60 * (h + 1))
                  for h in range(int(hrs))]
        gaps = [b.created_tick - a.created_tick for a, b in zip(win, win[1:])]
        per.append({
            "total": len(incs), "window": len(win), "rate": len(win) / hrs,
            "urg_rate": sum(i.code in ("A0", "A1") for i in win) / hrs,
            **{c: sum(i.code == c for i in win) for c in CODES},
            "urban": 100 * sum(metrics.is_urban(i.pos) for i in win) / len(win),
            "transport": 100 * sum(i.transport_needed for i in win) / len(win),
            "on_scene": {c: [i.on_scene_min for i in win if i.code == c] for c in CODES},
            "gap": st.mean(gaps), "max_gap": max(gaps), "busiest": max(hourly), "quietest": min(hourly),
            "hourly": hourly,
        })
    return per


def write_csv(loads, seeds, used_by):
    os.makedirs(OUT_DIR, exist_ok=True)
    n = 0
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["load", "seed", "used_by", "incident_id", "created_min", "phase", "hour_of_measured_day",
                    "code", "type", "description", "latitude", "longitude", "x_km", "y_km", "area",
                    "on_scene_min", "transport_needed", "hospital_stay_min"])
        for load in loads:
            for s in seeds:
                recs, incs = stream(load, s)
                by_id = {r["incident_id"]: r for r in recs}
                for i in incs:
                    r = by_id[i.incident_id]
                    t = i.created_tick
                    phase = "warm-up" if t < W0 else "measured" if t < W1 else "after"
                    w.writerow([load, s, used_by[load], i.incident_id, t, phase,
                                (t - W0) // 60 if phase == "measured" else "",
                                i.code, i.incident_type, r["incident"]["description"],
                                r["location"]["latitude"], r["location"]["longitude"],
                                round(i.pos[0], 2), round(i.pos[1], 2),
                                "urban" if metrics.is_urban(i.pos) else "rural",
                                i.on_scene_min, i.transport_needed, i.los_min])
                    n += 1
    return n


def main():
    high = float(open(rx.OUT_HIGH).read().strip())
    seeds = list(range(rx.SEED_BASE, rx.SEED_BASE + 30))
    exps = experiment_loads(high)
    loads = sorted({l for ls in exps.values() for l in ls})
    used_by = {l: "; ".join(e.split()[0] for e, ls in exps.items() if l in ls) for l in loads}
    stats = {l: load_stats(l, seeds) for l in loads}
    L = ["# Incidents used in the experiments", "",
         f"Generated by `experiments/export_incidents.py`. Every incident below is rebuilt exactly as the model "
         f"received it (same generator, seed and loader). Seeds {seeds[0]}–{seeds[-1]} (30 simulated days per "
         f"setting). Full list: `results/incidents/incidents.csv`, one row per incident.", "",
         "## How the incidents are made", "",
         f"* **Normal demand** = Twente's 2024 urgent volume, 23,238 A0+A1 dispatches a year "
         f"[Tweede Kamer 2025, nr. 747] = **{ec.URGENT_RATE_PER_HR:.2f} urgent calls/hour**. A2 calls are added "
         f"in the national ratio (A0+A1 = {ec.URGENT_SHARE_OF_EMERGENCY:.1%} of A0–A2 [RIVM/VZinfo]), giving "
         f"**{ec.NORMAL_RATE_PER_HR:.2f} calls/hour** in total. A load of 1.25× means 1.25 times that rate.",
         f"* **Number of calls per run is fixed** for a given load: rate × load × "
         f"{(ec.WARMUP_MIN + ec.WINDOW_MIN) / 60:g} h (4 h warm-up + 24 h measured), rounded. Every seed at the "
         "same load has the same count; what changes per seed is when, where and how urgent.",
         "* **Arrival times** are spread uniformly at random over the run, which is the same as a Poisson "
         "process with that number of calls (no day/night pattern). So the hourly counts below vary by chance.",
         "* **Urgency** is drawn per call from the national mix "
         + ", ".join(f"{c} {config.SEVERITY_MIX[c]:.1%}" for c in CODES) + " [RIVM/VZinfo].",
         "* **Location:** 75% near Enschede, Hengelo, Almelo or Oldenzaal (weights 5:3:2:1, ~2.5 km spread), 25% "
         "anywhere in the region `[ASSUMPTION]`. 'Urban' below = within 6 km of a city centre (the metric's "
         "definition), so some 'rural' draws count as urban and vice versa.",
         "* **On-scene time, transport and hospital stay** are drawn in advance per call (seeded), so every mode "
         "gets the identical patients.",
         f"* **Model clock:** minute 0 is the start of the generated stream (`generate_incidents.BASE_TIME`), "
         f"so the measured window covers a full 24 h of calls. Warm-up = minutes 0–{W0}, measured = {W0}–{W1}.",
         "* **Fixed on 2026-10-28:** earlier runs started the clock at each run's *first* call (on average 15 min "
         "into the stream at 1×, up to 43 min), which shifted the stream and left the last minutes of the "
         "measured day without new calls (4.23 vs 4.25 calls/h at 1×). All results were re-run after the fix.", "",
         "## Per experiment", "",
         "Calls/hour are counted in the 24 h measured window (calls in the warm-up are not measured). "
         "Values: mean over the 30 seeds (lowest–highest seed).", "",
         "| Experiment | Load | Calls per run | Target calls/h | Measured calls/h | Urgent (A0+A1)/h | Calls in 24 h measured |",
         "|---|---|---|---|---|---|---|"]
    for e, ls in exps.items():
        for l in ls:
            p = stats[l]
            L.append(f"| {e} | {l:g}× | {p[0]['total']} | {ec.NORMAL_RATE_PER_HR * l:.2f} | "
                     f"{summ([x['rate'] for x in p], 2)} | {summ([x['urg_rate'] for x in p], 2)} | "
                     f"{summ([x['window'] for x in p], 0)} |")
    L += ["", "Experiments at the same load share identical incidents: at 1× that is E1, E3 (1×), E5 and E6 (1×); "
          f"at {high:g}× it is E2 ({high:g}×), E3, E4, E4-switch and E6 at high load.", "",
          "## What the calls look like, per load (measured 24 h)", "",
          "| Load | A0 | A1 | A2 | Urban % | Needs transport % | Mean gap between calls (min) | "
          "Longest gap (min) | Busiest hour | Quietest hour |", "|---|---|---|---|---|---|---|---|---|---|"]
    for l in loads:
        p = stats[l]
        L.append(f"| {l:g}× | " + " | ".join(summ([x[c] for x in p], 0) for c in CODES) + " | "
                 f"{summ([x['urban'] for x in p], 0)} | {summ([x['transport'] for x in p], 0)} | "
                 f"{summ([x['gap'] for x in p], 1)} | {summ([x['max_gap'] for x in p], 0)} | "
                 f"{summ([x['busiest'] for x in p], 0)} | {summ([x['quietest'] for x in p], 0)} |")
    L += ["", "Busiest / quietest hour = the most / fewest calls in any one clock hour of the measured day.", "",
          "**Mean on-scene time (min)** per urgency (it does not depend on load): "
          + ", ".join(f"{c} {st.mean(v for x in stats[1.0] for v in x['on_scene'][c]):.1f}" for c in CODES)
          + " (all 1× calls pooled; some days have no A0 call at all).", "",
          "## Calls per hour of the measured day", "",
          "Mean over 30 seeds (lowest–highest). Hour 0 starts after the 4-hour warm-up. The variation is pure "
          "chance: the generator has no daily pattern.", "",
          f"| Hour | 1× (normal) | {high:g}× (high load) |", "|---|---|---|"]
    for h in range(24):
        L.append(f"| {h} | {summ([x['hourly'][h] for x in stats[1.0]], 1)} | "
                 f"{summ([x['hourly'][h] for x in stats[high]], 1)} |")

    # E4: how many urgent calls the outage and the switchover gap actually touch
    def urgent_in(a, b):
        out = []
        for s in seeds:
            _, incs = stream(high, s)
            out.append(sum(1 for i in incs if a <= i.created_tick < b and i.code in ("A0", "A1")))
        return out
    S = rx.OUTAGE_START
    L += ["", f"## E4: urgent calls that fall inside the outage ({high:g}× load)", "",
          f"The outage starts at model minute {S} (10 h into the measured day). E4's outage metrics use the A0+A1 "
          f"calls made during the outage and the {rx.OUTAGE_AFTER} min after it.", "",
          "| Outage (min) | Urgent calls during the outage | Urgent calls in outage + 60 min (the E4 metric) |",
          "|---|---|---|"]
    for o in rx.E4_OUTAGE:
        L.append(f"| {o} | {summ(urgent_in(S, S + o), 1) if o else '–'} | "
                 f"{summ(urgent_in(S, S + o + rx.OUTAGE_AFTER), 1)} |")
    L += ["", f"**E4-switch** ({rx.SWITCH_OUTAGE}-min outage): urgent calls made in the gap before the hybrid "
          "switches on (nothing is dispatched for them until it does).", "",
          "| Switchover delay (min) | Urgent calls in the gap |", "|---|---|"]
    for d in rx.SWITCH_DELAYS:
        L.append(f"| {d} | {summ(urgent_in(S, S + d), 1) if d else '0 (no gap)'} |")
    L += ["", "With only a handful of urgent calls in each outage window, a p95 over that window is close to "
          "the single slowest call; that is why the E4 p95 values have wide spreads between days.", ""]

    n = write_csv(loads, seeds, used_by)
    L += ["## The full list", "",
          f"`results/incidents/incidents.csv` — {n:,} rows, one per incident per (load, seed). Columns:", "",
          "| Column | Meaning |", "|---|---|",
          "| load, seed | demand level and simulated day |",
          "| used_by | experiments that ran on this stream |",
          "| incident_id | id within the run |",
          "| created_min | model minute of the 112 call |",
          "| phase, hour_of_measured_day | warm-up / measured / after; hour 0–23 of the measured day |",
          "| code | A0 (arrest), A1 (life-threatening), A2 (urgent) |",
          "| type, description | the schema record the voice-agent pipeline would produce |",
          "| latitude, longitude, x_km, y_km | location (real and model grid) |",
          "| area | urban (≤ 6 km from a city centre) or rural |",
          "| on_scene_min, transport_needed, hospital_stay_min | pre-drawn patient outcomes |"]
    open(OUT_MD, "w").write("\n".join(L) + "\n")
    print(f"wrote {OUT_MD} and {OUT_CSV} ({n:,} rows)")


if __name__ == "__main__":
    main()
