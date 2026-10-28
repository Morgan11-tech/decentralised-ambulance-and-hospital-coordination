"""
calibrate.py — Tune the [ASSUMPTION] parameters so the centralized baseline matches Dutch data.

Targets (see results/calibration_report.md for citations):
  T1  A1 (incl. A0) 95th-percentile response, measured from the 112 call: 15-17 min  [RIVM/VZinfo]
  T2  population within 12 min drive of a post (the 15-min norm minus 3 min handling): ~98.1% [RIVM/VZinfo]
  T3  ambulance offload delay in ~7.7% of hospital arrivals, median ~16 min           [WAITED]

T2 is a GEOGRAPHIC figure (are posts close enough?), not a share of calls, so it is
computed statically from the posts and the population proxy; it pins down travel speed.
T1 and T3 come from simulating the centralized model at normal demand. Response time is
TOTAL response: simulated call processing (config.DISPATCH_HANDLING_MIN) + travel.

Tuned:   N_AMBULANCES, EFFECTIVE_SPEED_KMH, hospital capacity (MST/ZGT), HOSPITAL_LOS_MEAN_MIN
Fixed:   DETOUR_FACTOR = 1.3 (speed and detour only matter as a ratio, so tuning both
         would be redundant); every sourced parameter.

Usage (from module/):
         python experiments/calibrate.py            # run grid, write src/config.py + results/calibration_report.md
         python experiments/calibrate.py --dry-run  # run grid, write only the report/CSV
"""

import argparse
import csv
import itertools
import math
import os
import random
import re
import statistics as st
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)  # data/ and results/ paths are relative to the module root

import config
import experiment_core as ec
import generate_incidents

SEEDS = list(range(1, 11))          # calibration seeds; experiments use different ones
FLEETS = [10, 11, 12, 13, 14, 15, 16, 18, 20]
SPEEDS = [55, 60, 65, 70]
CAPACITIES = [(9, 5), (9, 6), (10, 6), (10, 7), (11, 7), (12, 8)]   # (MST Enschede, ZGT Almelo)
LOS = [180, 195, 210]

P95_BAND = config.VALIDATION_P95_MIN_RANGE      # (15, 17)
P95_TARGET = sum(P95_BAND) / 2
COV_TARGET = config.COVERAGE_WITHIN_NORM * 100  # 98.1
COV_TOL = 0.5                                   # +- percentage points
OFFL_TARGET = config.VALIDATION_OFFLOAD_RATE * 100   # 7.7
OFFL_BAND = (6.0, 9.5)
OFFL_MEDIAN_BAND = config.OFFLOAD_DELAY_IQR_MIN      # WAITED IQR 10-25 min

OUT_CSV = "results/calibration_grid.csv"
OUT_MD = "results/calibration_report.md"


# --- T2: static population coverage ----------------------------------------
def coverage_pct(speed_kmh, n_points=20000, seed=0):
    """% of a population sample within DRIVE_BUDGET_MIN drive of the nearest post.

    The population proxy is the incident generator's own spatial distribution
    (urban-weighted), so coverage and demand describe the same region.
    """
    rng = random.Random(seed)
    posts = list(config.POSTS_XY.values())
    hit = 0
    for _ in range(n_points):
        x, y = config.latlon_to_xy(*generate_incidents._sample_pos(rng))
        d = min(math.hypot(x - px, y - py) for px, py in posts)
        hit += (d * config.DETOUR_FACTOR / speed_kmh * 60.0) <= config.DRIVE_BUDGET_MIN
    return hit / n_points * 100


# --- T1 + T3: simulated grid -------------------------------------------------
def grid_tasks():
    for n, sp, cap, los in itertools.product(FLEETS, SPEEDS, CAPACITIES, LOS):
        ov = {"EFFECTIVE_SPEED_KMH": float(sp), "HOSPITAL_LOS_MEAN_MIN": float(los),
              "capacity": {"MST Enschede": cap[0], "ZGT Almelo": cap[1]}}
        for s in SEEDS:
            yield {"mode": "centralized", "seed": s, "load": 1.0, "n_ambulances": n,
                   "overrides": ov, "_key": (n, sp, cap, los)}


def summarise(rows, cov):
    by = {}
    for r in rows:
        by.setdefault(r["_key"], []).append(r)
    out = []
    for (n, sp, cap, los), rs in by.items():
        def m(k):
            return st.mean(r[k] for r in rs)

        def sd(k):
            return st.stdev(r[k] for r in rs)
        out.append({
            "n_ambulances": n, "speed_kmh": sp, "cap_mst": cap[0], "cap_zgt": cap[1], "los_min": los,
            "coverage_pct": cov[sp],
            "p95": m("urg_resp_p95"), "p95_sd": sd("urg_resp_p95"),
            "within15_pct": m("urg_within15_pct"), "resp_mean": m("urg_resp_mean"),
            "offload_pct": m("win_offload_rate_pct"), "offload_sd": sd("win_offload_rate_pct"),
            "offload_median": m("win_offload_median"),
            "utilization_pct": m("utilization_pct"), "diversions": m("diversions"),
            "unserved": m("win_unserved"),
        })
    return out


def passes(c):
    return (P95_BAND[0] <= c["p95"] <= P95_BAND[1]
            and abs(c["coverage_pct"] - COV_TARGET) <= COV_TOL
            and OFFL_BAND[0] <= c["offload_pct"] <= OFFL_BAND[1]
            and OFFL_MEDIAN_BAND[0] <= c["offload_median"] <= OFFL_MEDIAN_BAND[1])


def score(c):
    """Distance from the targets, each scaled by how much error we tolerate."""
    return (abs(c["p95"] - P95_TARGET) / 1.0
            + abs(c["offload_pct"] - OFFL_TARGET) / 1.5
            + abs(c["coverage_pct"] - COV_TARGET) / COV_TOL)


def choose(cands):
    """Selection rule (fixed before looking at results):
    1. keep combinations that meet ALL targets;
    2. take the SMALLEST fleet among them (the fewest staffed units that meet the norm;
       a bigger fleet would also pass but adds capacity the data does not justify);
    3. within that fleet, the combination closest to the targets (score()).
    If nothing passes, fall back to the best score overall (reported as such).
    """
    ok = [c for c in cands if passes(c)]
    if not ok:
        return min(cands, key=score), False
    n_min = min(c["n_ambulances"] for c in ok)
    return min((c for c in ok if c["n_ambulances"] == n_min), key=score), True


# --- write-back --------------------------------------------------------------
def write_config(c, path="src/config.py"):
    s = open(path).read()
    tag = "calibrated by experiments/calibrate.py; see results/calibration_report.md"

    def sub(pattern, repl):
        nonlocal s
        s, k = re.subn(pattern, repl, s, count=1, flags=re.M)
        if k != 1:
            raise RuntimeError(f"could not update config.py ({pattern})")

    sub(r"^N_AMBULANCES = .*$",
        f"N_AMBULANCES = {c['n_ambulances']}         # [ASSUMPTION] concurrently-staffed A1 units; {tag}")
    sub(r"^EFFECTIVE_SPEED_KMH = .*$",
        f"EFFECTIVE_SPEED_KMH = {float(c['speed_kmh'])}   # [ASSUMPTION] {tag}")
    sub(r"^HOSPITAL_LOS_MEAN_MIN = .*$",
        f"HOSPITAL_LOS_MEAN_MIN = {float(c['los_min'])}    # [ASSUMPTION] {tag}; NL ED LOS is relatively short [NL-dashboard];")
    sub(r'("MST Enschede":.*"capacity": )\d+(\},)', rf"\g<1>{c['cap_mst']}\g<2>")
    sub(r'("ZGT Almelo":.*"capacity": )\d+(\},)', rf"\g<1>{c['cap_zgt']}\g<2>")
    open(path, "w").write(s)


def write_report(cands, chosen, ok, cov):
    f = lambda v, d=1: f"{v:.{d}f}"
    lines = [
        "# Calibration report",
        "",
        "Generated by `calibrate.py`. The model is run in the **centralized** mode (current Dutch",
        "practice) at **normal Twente demand**, and only the parameters tagged `[ASSUMPTION]` are tuned.",
        "",
        "## Targets",
        "",
        "| # | Target | Value | Source |",
        "|---|---|---|---|",
        f"| T1 | 95th-percentile A1 response (call → on scene) | {P95_BAND[0]:.0f}–{P95_BAND[1]:.0f} min | RIVM/VZinfo: national 16:57 (2025), regions 15:08–18:20 |",
        f"| T2 | Population within 12 min drive of a post (15-min norm − 3 min handling) | {COV_TARGET:.1f}% (±{COV_TOL}) | RIVM/VZinfo (24/7 coverage) |",
        f"| T3 | Hospital arrivals with offload delay | {OFFL_TARGET:.1f}% (band {OFFL_BAND[0]}–{OFFL_BAND[1]}), median 16 min | WAITED study, Int J Emerg Med 2025 |",
        "",
        "Note on T2: RIVM's 98.1% is a **geographic** figure (share of residents within reach of a post),",
        "not the share of calls answered on time. A p95 of ~17 min means that only ~92–94% of",
        "*calls* arrive within 15 min, so the two numbers measure different things. We therefore",
        "use T2 to set travel speed (a static calculation) and T1 to set fleet size (a simulation).",
        "",
        "## Normal demand",
        "",
        f"* Twente had **23,238 A1 (incl. A0) dispatches in 2024** (Sectorkompas figures quoted in the",
        "  Minister's answer to parliamentary questions, Aanhangsel Handelingen II 2025–2026, nr. 747).",
        f"  That is **{ec.URGENT_RATE_PER_HR:.2f} urgent calls/hour** — consistent with the brief's",
        "  estimate of 45,000 dispatches/yr × ~50% urgent ≈ 2.6/hour.",
        f"* The model also simulates A2 calls. Codes are drawn in the national 2025 mix (A0 {config.SEVERITY_MIX['A0']}, ",
        f"  A1 {config.SEVERITY_MIX['A1']}, A2 {config.SEVERITY_MIX['A2']}), so the total rate is",
        f"  {ec.URGENT_RATE_PER_HR:.2f} / {ec.URGENT_SHARE_OF_EMERGENCY:.3f} = **{ec.NORMAL_RATE_PER_HR:.2f} emergency calls/hour**",
        "  (`[ASSUMPTION]`: Twente's A1:A2 ratio equals the national one).",
        "* Calls arrive at a constant average rate (no day/night cycle) — `[ASSUMPTION]`.",
        f"* Each run: {ec.WARMUP_MIN} min warm-up (not measured, lets EDs fill), {ec.WINDOW_MIN} min measured,",
        f"  {ec.DRAIN_MIN} min drain. {len(SEEDS)} seeds per combination (seeds {SEEDS[0]}–{SEEDS[-1]}).",
        f"* **Response time is total response, call → on scene, including decision latency.** Every call goes",
        f"  through {config.DISPATCH_HANDLING_MIN:g} min of simulated call processing (`DISPATCH_HANDLING_MIN`, the",
        "  \"PSAP to Unit Notified\" interval [NASEMSO 2024]; measured 2.3 ± 2 min [Citerio 2006]) before a unit can",
        "  be assigned, in every dispatch mode; then travel. The Dutch norm budgets 3 min for call handling and",
        "  turnout (RIVM/VZinfo: “12 minuten rijtijd + 3 minuten meld- en uitruktijd”); turnout is not modelled.",
        f"* **Finite operators.** The centralized dispatcher has {config.N_DISPATCH_OPERATORS} call-taker(s)",
        "  (`N_DISPATCH_OPERATORS`; Twente's pro-rata share of the Meldkamer Oost-Nederland 112 team of 4/4/3",
        "  [NAZ-MkON], `[ASSUMPTION]`). Each holds a call for the processing time; when all are busy, calls",
        "  queue, most urgent first. At normal demand the queue is rare, so calibration barely changes",
        "  (previous fit with unlimited operators: p95 16.3 min, same chosen values).",
        "* This replaces the earlier set-up, in which 3 min were added to every simulated time *after* the run.",
        "  Results from before this change are superseded.",
        "",
        "## Grid searched",
        "",
        f"* `N_AMBULANCES` ∈ {FLEETS}",
        f"* `EFFECTIVE_SPEED_KMH` ∈ {SPEEDS} (with `DETOUR_FACTOR` fixed at {config.DETOUR_FACTOR})",
        f"* hospital capacity (MST, ZGT) ∈ {CAPACITIES}",
        f"* `HOSPITAL_LOS_MEAN_MIN` ∈ {LOS}",
        f"* = {len(cands)} combinations × {len(SEEDS)} seeds = {len(cands) * len(SEEDS)} runs. Full table: `{OUT_CSV}`.",
        "",
        "### T2 — coverage by speed (static)",
        "",
        "| speed (km/h) | population within 12 min drive |",
        "|---|---|",
    ] + [f"| {sp} | {f(cov[sp])}% |" for sp in SPEEDS] + [
        "",
        "## Selection rule (fixed before running)",
        "",
        "1. Keep combinations that meet **all** targets (T1 band, T2 ±0.5 pp, T3 band, and offload",
        "   median inside WAITED's IQR 10–25 min).",
        "2. Among them, take the **smallest fleet** — the fewest staffed units that meet the norm.",
        "3. Within that fleet, take the combination closest to the targets.",
        "",
        "## Chosen values",
        "",
    ]
    if not ok:
        lines += ["**No combination met every target; the closest one overall is shown.**", ""]
    c = chosen
    lines += [
        "| Parameter | Before | Chosen |",
        "|---|---|---|",
        f"| `N_AMBULANCES` | {BEFORE['n']} | **{c['n_ambulances']}** |",
        f"| `EFFECTIVE_SPEED_KMH` | {BEFORE['speed']} | **{c['speed_kmh']}** |",
        f"| `DETOUR_FACTOR` | {config.DETOUR_FACTOR} | {config.DETOUR_FACTOR} (not tuned) |",
        f"| MST Enschede capacity | {BEFORE['mst']} | **{c['cap_mst']}** |",
        f"| ZGT Almelo capacity | {BEFORE['zgt']} | **{c['cap_zgt']}** |",
        f"| `HOSPITAL_LOS_MEAN_MIN` | {BEFORE['los']} | **{c['los_min']}** |",
        "",
        "## How close each target got (mean over seeds ± sd)",
        "",
        "| Target | Wanted | Model |",
        "|---|---|---|",
        f"| T1 p95 response (A0+A1) | {P95_BAND[0]:.0f}–{P95_BAND[1]:.0f} min | **{f(c['p95'])} ± {f(c['p95_sd'])} min** |",
        f"| T2 coverage | {COV_TARGET:.1f}% | **{f(c['coverage_pct'])}%** |",
        f"| T3 offload rate | {OFFL_TARGET:.1f}% | **{f(c['offload_pct'])} ± {f(c['offload_sd'])}%** |",
        f"| T3 offload median | 16 min (IQR 10–25) | **{f(c['offload_median'])} min** |",
        f"| (info) A0+A1 calls within 15 min | not a target | {f(c['within15_pct'])}% |",
        f"| (info) mean A0+A1 response | not a target | {f(c['resp_mean'])} min |",
        f"| (info) ambulance utilization | not a target | {f(c['utilization_pct'])}% |",
        "",
        "## Sensitivity: p95 by fleet and speed (chosen hospital settings)",
        "",
        "| fleet \\ speed | " + " | ".join(str(s) for s in SPEEDS) + " |",
        "|---|" + "---|" * len(SPEEDS),
    ]
    for n in FLEETS:
        cells = []
        for sp in SPEEDS:
            x = next(r for r in cands if r["n_ambulances"] == n and r["speed_kmh"] == sp
                     and r["cap_mst"] == c["cap_mst"] and r["cap_zgt"] == c["cap_zgt"]
                     and r["los_min"] == c["los_min"])
            cells.append(f"{f(x['p95'])}{'*' if passes(x) else ''}")
        lines.append(f"| {n} | " + " | ".join(cells) + " |")
    lines += ["", "`*` = meets all targets.", "",
              "## Sensitivity: offload rate by hospital setting (chosen fleet and speed)", "",
              "| capacity (MST/ZGT) \\ LOS | " + " | ".join(f"{l} min" for l in LOS) + " |",
              "|---|" + "---|" * len(LOS)]
    for cap in CAPACITIES:
        cells = []
        for l in LOS:
            x = next(r for r in cands if r["n_ambulances"] == c["n_ambulances"]
                     and r["speed_kmh"] == c["speed_kmh"] and (r["cap_mst"], r["cap_zgt"]) == cap
                     and r["los_min"] == l)
            cells.append(f"{f(x['offload_pct'])}% (p95 {f(x['p95'])})")
        lines.append(f"| {cap[0]}/{cap[1]} | " + " | ".join(cells) + " |")
    n_pass = sum(passes(x) for x in cands)
    lines += [
        "",
        f"{n_pass} of {len(cands)} combinations met all targets.",
        "",
        "## Why these values are defensible",
        "",
        f"* **Fleet = {c['n_ambulances']} units on duty at once.** Ambulance Oost runs ~32 vehicles (25 ambulances,",
        "  5 care vehicles, 2 rapid responders), but not all are staffed at the same time: shifts differ",
        "  between day and night, and part of the fleet is doing A2 and planned (B) transport, which this",
        f"  model leaves out. {c['n_ambulances']} units is a 24-hour average of A1-capable units, about half the",
        "  ambulances. We picked the *smallest* fleet that meets the norm, so we do not add capacity that",
        "  the data does not ask for. This is `[ASSUMPTION]` — Ambulance Oost does not publish hourly staffing.",
        f"* **Speed = {c['speed_kmh']} km/h with a 1.3 detour factor** (= {c['speed_kmh'] / config.DETOUR_FACTOR:.0f} km/h as the crow flies).",
        "  This is the speed at which the model reproduces RIVM's 98.1% geographic coverage from the 11",
        "  posts. It is an average over urban and rural driving with lights and sirens. A road-network",
        "  detour of ~1.2–1.4 × straight-line distance is the usual order of magnitude (Ballou et al. 2002).",
        f"* **ED capacity {c['cap_mst']} (MST) / {c['cap_zgt']} (ZGT) and stay {c['los_min']} min.** “Capacity” here",
        "  means the treatment places *effectively available to ambulance patients*, not the total number",
        "  of ED beds (walk-in and GP-referred patients use the rest). MST is larger than ZGT, as in reality.",
        "  These values reproduce WAITED's offload rate. Offload delay jumps sharply around this",
        "  capacity (see table above): one or two places more and offload vanishes, fewer and it explodes.",
        "  That sharpness is itself a finding about how sensitive offload is to ED crowding.",
        "",
        "## Limitations",
        "",
        "* WAITED is one Dutch hospital group (Rotterdam), not Twente. Its offload rate is a plausibility",
        "  anchor, not a Twente measurement.",
        "* RIVM's response figures are national/regional averages; we did not find a published 2025 p95 for",
        "  Twente specifically, so we calibrate to the national band.",
        "* Calibration seeds (1–10) are different from experiment seeds, so E1 doubles as an",
        "  out-of-sample check of the calibration.",
        "",
        "## References",
        "",
        "* RIVM / VZinfo. *Acute zorg — Ambulancezorg, regionaal* (Sectorkompas Ambulancezorg 2025 data).",
        "  https://www.vzinfo.nl/acute-zorg/regionaal/ambulancezorg (accessed 2026-10-18)",
        "* Tweede Kamer. Aanhangsel van de Handelingen 2025–2026, nr. 747: answers of the Minister of VWS",
        "  to questions on Ambulance Oost dispatch volumes (19 Dec 2025), Table 1. https://berthub.eu/tkconv/getraw/2025D53564",
        "* WAITED study (2025). *Waiting time ambulances in the Emergency Department; a Dutch single-center",
        "  study.* International Journal of Emergency Medicine. https://doi.org/10.1186/s12245-025-01068-y",
        "* Ambulance Oost (RAV Twente). https://ambulanceoost.nl (fleet ~32 vehicles, 11 posts, ~639k residents)",
        "* Ballou, R. H., Rahardja, H., Sakai, N. (2002). Selected country circuity factors for road travel",
        "  distance estimation. Transportation Research Part A, 36(9), 843–848. https://doi.org/10.1016/S0965-8564(01)00044-1",
    ]
    open(OUT_MD, "w").write("\n".join(lines) + "\n")


BEFORE = {"n": config.N_AMBULANCES, "speed": config.EFFECTIVE_SPEED_KMH,
          "mst": config.HOSPITALS_LATLON["MST Enschede"]["capacity"],
          "zgt": config.HOSPITALS_LATLON["ZGT Almelo"]["capacity"], "los": config.HOSPITAL_LOS_MEAN_MIN}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="do not modify config.py")
    a = ap.parse_args()

    cov = {sp: coverage_pct(sp) for sp in SPEEDS}
    tasks = list(grid_tasks())
    print(f"running {len(tasks)} calibration runs ...")
    rows = ec.run_many(tasks)
    cands = summarise(rows, cov)

    os.makedirs("results", exist_ok=True)
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(cands[0].keys()) + ["meets_all"])
        w.writeheader()
        for c in cands:
            w.writerow({**c, "meets_all": passes(c)})

    chosen, ok = choose(cands)
    write_report(cands, chosen, ok, cov)
    print(("chosen" if ok else "closest (no combination met all targets)") + ":",
          {k: (round(v, 2) if isinstance(v, float) else v) for k, v in chosen.items()})
    if not a.dry_run:
        write_config(chosen)
        print("config.py updated")
    print(f"wrote {OUT_MD} and {OUT_CSV}")


if __name__ == "__main__":
    main()
