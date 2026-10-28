"""
analyze.py — Figures and tables from results/experiments.csv.

  python experiments/analyze.py   -> results/figures/*.png and results/tables.md

Every resilience figure: stress on x, performance on y, one line per mode,
line = mean over seeds, shaded band = interquartile range (25th-75th percentile) over
seeds (response times are skewed, so +-sd would dip below zero), dashed 15-min norm.

Modes: A = centralized (dispatcher with finite operators), B = decentralized (Contract Net).
Both serve the most urgent calls first. H = hybrid (A, falling back to B while the dispatcher is
down) appears in E4 and E4-switch only; there it is compared paired against A and against B.

Crossover: because both modes run on identical incidents per seed, we compare them
PAIRED: D = B - A for each seed, with a 95% t-interval per point.
A crossover is reported as the bracket of swept values between which D changes sign,
using only points where D is significant (so noise is not called a crossover).
"""

import os
import shutil
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)  # data/ and results/ paths are relative to the module root

IN_CSV = "results/experiments.csv"
IN_TIMELINE = "results/e4_timeline.csv"
FIG_DIR = "results/figures"
OUT_MD = "results/tables.md"
PRESENT_DIR = "results/presentation"
# the figures worth showing; presentation_notes.md in PRESENT_DIR explains each one
PRESENTATION = ["E2_load_p95_unserved.png", "E3_message_loss.png", "E4_outage_p95.png",
                "E4_switchover_delay.png", "E5_bid_window.png", "E6_operators.png"]

# Fixed colour per mode in every figure: centralized = blue, decentralized = purple, hybrid = green.
# Checked with the dataviz palette validator (light surface, all pairs): passes colour-blind
# separation and the normal-vision floor. Every line also carries a direct label and its own
# marker, and every figure has a table in tables.md.
MODES = ("centralized", "decentralized", "hybrid")
COLORS = {"centralized": "#2a78d6", "decentralized": "#a23b9e", "hybrid": "#1f8a4c"}
LABELS = {"centralized": "Centralized (A)", "decentralized": "Decentralized (B)",
          "hybrid": "Hybrid (H): A, B while dispatcher down"}
SHORT = {"centralized": "A", "decentralized": "B", "hybrid": "H"}
MARKERS = {"centralized": "o", "decentralized": "s", "hybrid": "^"}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
NORM = 15.0          # A1 norm [RIVM/VZinfo]
A2_NORM = 30.0       # A2 norm [AZN 2019]
DPI = 200

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titlesize": 11, "axes.titleweight": "bold", "legend.frameon": False,
})


# --- statistics ----------------------------------------------------------------
def agg(df, x, y):
    g = df.groupby([x, "mode"])[y]
    return pd.DataFrame({"mean": g.mean(), "q25": g.quantile(0.25),
                         "q75": g.quantile(0.75)}).reset_index()


def modes_in(df):
    present = set(df["mode"].unique())
    return [m for m in MODES if m in present]


def paired(df, x, y, a="centralized", b="decentralized"):
    """Per swept value: mean, sd of modes a and b, and the paired difference b - a with 95% CI.
    (Columns keep the names cen_*/dec_* for a/b.)"""
    rows = []
    for v, sub in df.groupby(x):
        c = sub[sub["mode"] == a].set_index("seed")[y]
        d = sub[sub["mode"] == b].set_index("seed")[y]
        diff = (d - c).dropna()
        n = len(diff)
        half = stats.t.ppf(0.975, n - 1) * diff.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
        rows.append({x: v, "cen_mean": c.mean(), "cen_sd": c.std(), "dec_mean": d.mean(),
                     "dec_sd": d.std(), "diff": diff.mean(), "ci_lo": diff.mean() - half,
                     "ci_hi": diff.mean() + half,
                     "significant": bool(n > 1 and (diff.mean() - half > 0 or diff.mean() + half < 0))})
    return pd.DataFrame(rows)


def crossovers(p, x):
    """Brackets (lo, hi) where the paired difference changes sign BETWEEN SIGNIFICANT points.

    Points whose 95% interval includes 0 are skipped, so two modes that are both at
    ~0% unserved do not produce a spurious crossover. We report the bracket between the
    last significant point of one sign and the first of the other, not an interpolated
    value: with a coarse sweep and steep curves, interpolation would invent precision.
    """
    sig = p[p["significant"]]
    xs, ds = sig[x].to_numpy(float), sig["diff"].to_numpy(float)
    return [(xs[i], xs[i + 1]) for i in range(len(xs) - 1) if ds[i] * ds[i + 1] < 0]


def crossover_text(p, x, unit="", higher_better=False, a="centralized", b="decentralized"):
    """Plain-language verdict. diff = b - a; for times lower is better."""
    better_dec = (p["diff"] > 0) if higher_better else (p["diff"] < 0)
    sig = p["significant"]
    cx = crossovers(p, x)
    if cx:
        return "crossover between " + ", ".join(f"{lo:g} and {hi:g}{unit}" for lo, hi in cx)
    if not sig.any():
        return "no significant difference at any value"
    if (better_dec[sig]).all():
        return f"{SHORT[b]} better wherever the difference is significant ({sig.sum()}/{len(p)} values)"
    if (~better_dec[sig]).all():
        return f"{SHORT[a]} better wherever the difference is significant ({sig.sum()}/{len(p)} values)"
    return "mixed"


# --- plotting ------------------------------------------------------------------
def line_panel(ax, df, x, y, ylabel, title, norm=False, logy=False, xlabel=None, annotate=True):
    g = agg(df, x, y)
    ends = {}
    for mode in modes_in(df):
        s = g[g["mode"] == mode].sort_values(x)
        xs, m = s[x].to_numpy(float), s["mean"].to_numpy(float)
        ax.fill_between(xs, s["q25"].to_numpy(float), s["q75"].to_numpy(float),
                        color=COLORS[mode], alpha=0.15, linewidth=0)
        ax.plot(xs, m, color=COLORS[mode], lw=2, marker=MARKERS[mode], ms=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=LABELS[mode])
        ends[mode] = (xs[-1], m[-1])
    if logy:
        ax.set_yscale("log")
    elif y.endswith("_pct"):
        ax.set_ylim(bottom=0, top=max(ax.get_ylim()[1], 5))
    if norm:
        _norm_line(ax, NORM if norm is True else norm)
    if annotate:
        if len(modes_in(df)) == 2:
            for i, (lo, hi) in enumerate(crossovers(paired(df, x, y), x)):
                ax.axvspan(lo, hi, color=INK, alpha=0.06, linewidth=0)
                ax.annotate(f"crossover in {lo:g}–{hi:g}", ((lo + hi) / 2, 0.97 - 0.07 * i),
                            xycoords=("data", "axes fraction"), ha="center", va="top",
                            fontsize=8, color=INK)
    ax.set_xlabel(xlabel or x)
    ax.set_ylabel(ylabel)
    ax.set_title(title, loc="left")
    ax.margins(x=0.12)
    _direct_labels(ax, ends)


def _norm_line(ax, value=NORM):
    ax.axhline(value, color=INK2, lw=1, ls="--")
    label = f"{value:g}-min norm" + (" (A2)" if value == A2_NORM else "")
    ax.annotate(label, (ax.get_xlim()[0], value), xytext=(4, 3),
                textcoords="offset points", fontsize=8, color=INK2)


def _direct_labels(ax, ends, gap_pt=11.0):
    """Label each line at its right end (anchored to the data point). Call after all
    artists are added; labels closer than gap_pt are spread apart around their centre."""
    ax.autoscale_view()
    px_per_pt = ax.figure.dpi / 72.0
    order = sorted(ends, key=lambda m: ax.transData.transform(ends[m])[1])
    ys = [ax.transData.transform(ends[m])[1] / px_per_pt for m in order]
    placed = list(ys)
    for i in range(1, len(placed)):                    # push upwards to keep the gap
        placed[i] = max(placed[i], placed[i - 1] + gap_pt)
    shift = (sum(ys) - sum(placed)) / len(ys)          # re-centre the group on the data
    for m, y0, y1 in zip(order, ys, placed):
        ax.annotate(SHORT[m], ends[m], xytext=(6, y1 + shift - y0), textcoords="offset points",
                    va="center", fontsize=9, color=INK2, annotation_clip=False)


def save(fig, name, note=None):
    if note:
        fig.text(0.01, 0.005, note, fontsize=8, color=INK2, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 0.93))
    os.makedirs(FIG_DIR, exist_ok=True)
    fig.savefig(os.path.join(FIG_DIR, name), dpi=DPI)
    plt.close(fig)


def legend_top(fig, ax):
    h, l = ax.get_legend_handles_labels()
    fig.legend(h, l, loc="upper left", bbox_to_anchor=(0.01, 0.995), ncol=len(h), fontsize=9)


BAND_NOTE = ("Line = mean over seeds; band = interquartile range over seeds. "
             "Response = 112 call → on scene, A0+A1 calls.")


def _ref_line(ax, value, color, ls, text, dy=0):
    """Horizontal reference (a rule that has no window to sweep), labelled at the right edge."""
    ax.axhline(value, color=color, lw=1.6, ls=ls)
    ax.annotate(text, (1.0, value), xycoords=("axes fraction", "data"), xytext=(4, dy),
                textcoords="offset points", va="center", fontsize=8, color=INK2, annotation_clip=False)


def e5_figure(d):
    """Bidding-window sweep at normal demand: the everyday cost of the auction."""
    w = d[d.experiment == "E5"]
    if w.empty:
        return
    B, A = "decentralized", "centralized"
    dec = w[w["mode"] == B]
    ok = dec[dec.win_unserved_pct < 100]
    failed = sorted(dec[dec.win_unserved_pct >= 100]["swept_value"].unique())
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, y, what in ((axs[0], "urg_resp_mean", "Mean"), (axs[1], "urg_resp_p95", "p95")):
        g = ok.groupby("swept_value")[y]
        xs = np.array(sorted(ok["swept_value"].unique()), float)
        ax.fill_between(xs, g.quantile(0.25).loc[xs], g.quantile(0.75).loc[xs], color=COLORS[B],
                        alpha=0.15, linewidth=0)
        ax.plot(xs, g.mean().loc[xs], color=COLORS[B], lw=2, marker=MARKERS[B], ms=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=LABELS[B])
        ref_a = w[w["mode"] == A][y].mean()
        ax.plot([], [], color=COLORS[A], lw=1.6, label=LABELS[A] + ", no window")
        _ref_line(ax, ref_a, COLORS[A], "-", f"A {ref_a:.1f}")
        if what == "p95":
            _norm_line(ax)
        ax.set_ylim(0, max(ok[y].quantile(0.75), ref_a, NORM) * 1.3)
        for x in failed:
            ax.plot([x], [0.93], transform=ax.get_xaxis_transform(), marker="X", ms=9,
                    color=COLORS[B], markeredgecolor=SURFACE, clip_on=False)
        if failed:
            ax.annotate("✕ = no call ever assigned:\nthe auction closes before any bid arrives",
                        (min(failed) + 0.08, 0.86), xycoords=("data", "axes fraction"), fontsize=8,
                        color=INK2, va="top")
        ax.set_xticks(sorted(dec["swept_value"].unique()))
        ax.set_xlabel("bidding window (min)")
        ax.set_ylabel(f"{what} response, A0+A1 (min)")
        ax.set_title(f"E5 · {what} response vs bidding window", loc="left")
        ax.margins(x=0.1)
    legend_top(fig, axs[0])
    save(fig, "E5_bid_window.png",
         "Normal demand, perfect comms. Line = mean over seeds, band = interquartile range. "
         "Ticks are 1 min, so 1 min is the shortest workable window.")


def _op_x(df):
    """Operators on an evenly spaced axis, with 'unlimited' as the last tick."""
    order = sorted(df["swept_value"].unique())
    pos = {v: i for i, v in enumerate(order)}
    return df.assign(op_x=df["swept_value"].map(pos)), order


def _op_ticks(ax, order):
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(["∞" if v >= 100 else f"{v:g}" for v in order])
    ax.set_xlabel("dispatch operators on shift (centralized)")


def e6_figure(d, high):
    """Operator capacity: how much the centralized result depends on call-taker staffing."""
    e6 = d[d.experiment == "E6"]
    if e6.empty:
        return
    e6, order = _op_x(e6)
    fig, axs = plt.subplots(1, 3, figsize=(15.5, 4.6))
    for ax, load in zip(axs[:2], (1.0, high)):
        line_panel(ax, e6[e6.load == load], "op_x", "urg_resp_p95", "p95 response, A0+A1 (min)",
                   f"E6 · p95 vs operators, {load:g}× demand", norm=True)
        _op_ticks(ax, order)
    # operator queueing vs demand, from E2 (1 operator), against total time to assignment
    ax = axs[2]
    e2 = d[(d.experiment == "E2") & (d["mode"] == "centralized")]
    for y, ls, text in (("urg_wait_operator_mean", "-", "waiting for an operator"),
                        ("urg_wait_assign_mean", "--", "call → unit assigned (total)")):
        g = e2.groupby("load")[y]
        xs = np.array(sorted(e2["load"].unique()), float)
        ax.fill_between(xs, g.quantile(0.25).loc[xs], g.quantile(0.75).loc[xs],
                        color=COLORS["centralized"], alpha=0.15, linewidth=0)
        ax.plot(xs, g.mean().loc[xs], color=COLORS["centralized"], lw=2, ls=ls,
                marker=MARKERS["centralized"], ms=5, markeredgecolor=SURFACE, label=text)
        ax.annotate(text, (xs[-1], g.mean().loc[xs[-1]]), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=8, color=INK2, annotation_clip=False)
    ax.set_yscale("log")
    ax.set_xlabel("demand (× normal)")
    ax.set_ylabel("mean minutes, A0+A1 (log)")
    ax.set_title(f"E2 · Where centralized calls wait ({e2.n_operators.iloc[0]:g} operator)", loc="left")
    ax.margins(x=0.08)
    legend_top(fig, axs[0])
    save(fig, "E6_operators.png",
         "Left, middle: line = mean over seeds, band = interquartile range; ∞ = unlimited operators. "
         "Right: centralized only; the operator queue is a small part of the wait for a unit.")


def _hybrid_departs(ax, e4, y):
    """Mark the first outage length at which H differs significantly from A (paired)."""
    if "hybrid" not in modes_in(e4):
        return
    p = paired(e4, "outage_len", y, "centralized", "hybrid")
    sig = p[p["significant"]]
    ax.annotate("H = A when the\ndispatcher never fails", (0, 0.40), xycoords=("data", "axes fraction"),
                xytext=(-4, 0), textcoords="offset points", fontsize=8, color=INK2)
    if not sig.empty:
        x0 = sig["outage_len"].min()
        ax.axvline(x0, color=COLORS["hybrid"], lw=1, ls=":")
        ax.annotate(f"H below A from {x0:g} min\n(paired 95% CI)", (x0, 0.70),
                    xycoords=("data", "axes fraction"), xytext=(4, 0), textcoords="offset points",
                    fontsize=8, color=INK2)


def e4_switch_figure(d, high):
    """Hybrid's switchover delay at one outage length: how fast must the fallback switch on?"""
    w = d[d.experiment == "E4-switch"]
    if w.empty:
        return
    H = w[w["mode"] == "hybrid"]
    L = int(w.outage_len.iloc[0])
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, y, what in ((axs[0], "ev_urg_resp_p95", "p95"), (axs[1], "ev_urg_resp_mean", "Mean")):
        g = H.groupby("swept_value")[y]
        xs = np.array(sorted(H["swept_value"].unique()), float)
        ax.fill_between(xs, g.quantile(0.25).loc[xs], g.quantile(0.75).loc[xs],
                        color=COLORS["hybrid"], alpha=0.15, linewidth=0)
        ax.plot(xs, g.mean().loc[xs], color=COLORS["hybrid"], lw=2, marker=MARKERS["hybrid"], ms=7,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=LABELS["hybrid"])
        top = g.quantile(0.75).max()
        for m, ls, dy in (("centralized", "-", 0), ("decentralized", "--", 0)):
            ref = w[w["mode"] == m][y].mean()
            ax.plot([], [], color=COLORS[m], lw=1.6, ls=ls, label=LABELS[m] + ", no switch")
            _ref_line(ax, ref, COLORS[m], ls, f"{SHORT[m]} {ref:.1f}", dy)
            top = max(top, ref)
        if what == "p95":
            _norm_line(ax)
        ax.set_ylim(0, max(top, NORM) * 1.15)
        ax.set_xticks(xs)
        ax.set_xlabel("switchover delay: minutes to notice the outage / recovery")
        ax.set_ylabel(f"{what} response, A0+A1 (min)")
        ax.set_title(f"E4-switch · {what}, calls during {L}-min outage (+60 min)", loc="left")
        ax.margins(x=0.1)
    legend_top(fig, axs[0])
    save(fig, "E4_switchover_delay.png",
         f"{high:g}× demand, {L}-min outage. Line = mean over seeds, band = interquartile range. "
         "During the delay after onset nothing is dispatched; after recovery units keep bidding as long.")


def figures(d, high):
    os.makedirs(FIG_DIR, exist_ok=True)
    for f in os.listdir(FIG_DIR):                     # no stale figures from older runs
        if f.endswith(".png"):
            os.remove(os.path.join(FIG_DIR, f))
    e2 = d[d.experiment == "E2"]
    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    line_panel(axs[0], e2, "load", "urg_resp_p95", "p95 response (min, log scale)",
               "E2 · Urgent p95 vs demand", norm=True, logy=True, xlabel="demand (× normal Twente rate)")
    line_panel(axs[1], e2, "load", "win_unserved_pct", "calls unfinished at end of run (%)",
               "E2 · Unserved calls vs demand", xlabel="demand (× normal Twente rate)")
    legend_top(fig, axs[0]); save(fig, "E2_load_p95_unserved.png", BAND_NOTE)

    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    line_panel(axs[0], e2, "load", "urg_resp_p95", "p95 response (min, log scale)",
               "E2 · A0+A1 (urgent) calls", norm=True, logy=True, xlabel="demand (× normal)")
    line_panel(axs[1], e2, "load", "a2_resp_p95", "p95 response (min, log scale)",
               "E2 · A2 (less urgent) calls", norm=A2_NORM, logy=True, xlabel="demand (× normal)")
    legend_top(fig, axs[0])
    save(fig, "E2_load_urgent_vs_A2.png",
         "Both modes serve urgent calls first, so less urgent (A2) calls take the wait.")

    fig, axs = plt.subplots(1, 2, figsize=(11, 4.2))
    line_panel(axs[0], d[d.experiment == "E2"], "load", "msgs_total", "messages sent per simulated day (log)",
               "E2 · Coordination overhead vs demand", logy=True, xlabel="demand (× normal)", annotate=False)
    line_panel(axs[1], d[d.experiment == "E2"], "load", "urg_wait_assign_mean",
               "mean time from call to unit assigned (min)", "E2 · Time to assign a unit (A0+A1)",
               xlabel="demand (× normal)", annotate=False)
    legend_top(fig, axs[0])
    save(fig, "E2_load_messages_assign_time.png", "Line = mean over seeds; band = interquartile range. "
         "Assignment time includes the 2-min call processing for every mode.")

    for exp, var, xl, fname in (("E3-loss", "loss_prob", "message loss probability (per message)",
                                 "E3_message_loss.png"),
                                ("E3-delay", "delay_ticks", "message delay (min)", "E3_message_delay.png")):
        e3 = d[d.experiment == exp]
        fig, axs = plt.subplots(2, 2, figsize=(11, 7.6))
        for r, load in enumerate((1.0, high)):
            sub = e3[e3.load == load]
            line_panel(axs[r, 0], sub, var, "urg_resp_p95", "p95 response (min)",
                       f"{exp} · p95 at {load:g}× demand", norm=True, xlabel=xl)
            line_panel(axs[r, 1], sub, var, "win_unserved_pct", "calls unfinished at end (%)",
                       f"{exp} · Unserved at {load:g}× demand", xlabel=xl)
        legend_top(fig, axs[0, 0]); save(fig, fname, BAND_NOTE)

    e4 = d[d.experiment == "E4"]
    fig, axs = plt.subplots(1, 3, figsize=(15.5, 4.6))
    line_panel(axs[0], e4, "outage_len", "ev_urg_resp_p95", "p95 response (min)",
               f"E4 · Calls during outage (+60 min), {high:g}×", norm=True,
               xlabel="dispatcher outage length (min)")
    _hybrid_departs(axs[0], e4, "ev_urg_resp_p95")
    line_panel(axs[1], e4, "outage_len", "urg_resp_p95", "p95 response (min)",
               f"E4 · Whole measured day, {high:g}×", norm=True,
               xlabel="dispatcher outage length (min)")
    line_panel(axs[2], e4, "outage_len", "win_unserved_pct", "calls unfinished at end (%)",
               f"E4 · Unserved calls, {high:g}×", xlabel="dispatcher outage length (min)")
    legend_top(fig, axs[0])
    save(fig, "E4_outage_p95.png", BAND_NOTE + " Only A and H have a dispatcher that can fail; "
         "H switches to bidding during the outage (switchover delay 0 = best case).")
    e4_switch_figure(d, high)

    e5_figure(d)
    e6_figure(d, high)

    if os.path.exists(IN_TIMELINE):
        import run_experiments as rx
        tl = pd.read_csv(IN_TIMELINE)
        tl = tl[tl.code.isin(["A0", "A1"])]
        tl["t_rel"] = tl.created_tick - rx.OUTAGE_START
        tl = tl[(tl.t_rel >= -120) & (tl.t_rel < 360)]
        tl["bin"] = (tl.t_rel // 20) * 20 + 10
        fig, axs = plt.subplots(1, 2, figsize=(11, 4.4))
        for ax, L in zip(axs, (60, 120)):
            for mode in modes_in(tl):
                s = tl[(tl.outage_len == L) & (tl["mode"] == mode)]
                g = s.groupby(["bin", "seed"]).response_min.mean().groupby("bin")
                per = pd.DataFrame({"mean": g.mean(), "q25": g.quantile(0.25), "q75": g.quantile(0.75)})
                ax.fill_between(per.index, per["q25"], per["q75"],
                                color=COLORS[mode], alpha=0.15, linewidth=0)
                ax.plot(per.index, per["mean"], color=COLORS[mode], lw=2, label=LABELS[mode])
            ax.axvspan(0, L, color=INK2, alpha=0.08, linewidth=0)
            ax.annotate("dispatcher down", (L / 2, 0.95), xycoords=("data", "axes fraction"),
                        ha="center", fontsize=8, color=INK2)
            if "hybrid" in modes_in(tl):
                for x, text, ha in ((0, "H leaves A:\nunits bid ▸", "right"),
                                    (L, "◂ H rejoins A:\ndispatcher back", "left")):
                    ax.axvline(x, color=COLORS["hybrid"], lw=1, ls=":")
                    ax.annotate(text, (x, 0.80), xycoords=("data", "axes fraction"), xytext=(-4 if ha == "right" else 4, 0),
                                textcoords="offset points", ha=ha, fontsize=8, color=INK2)
            _norm_line(ax)
            ax.set_title(f"E4 · Recovery, {L}-min outage, {high:g}× demand", loc="left")
            ax.set_xlabel("call created (min after outage start)")
            ax.set_ylabel("mean A0+A1 response (min)")
        legend_top(fig, axs[0])
        save(fig, "E4_outage_recovery_timeline.png",
             "Mean response of A0+A1 calls created in each 20-min bin; band = interquartile range over seeds.")


# --- summary tables ------------------------------------------------------------
def fmt(v, d=1):
    return "–" if pd.isna(v) else f"{v:.{d}f}"


def _diff_cell(r, d=1):
    sig = "" if r["significant"] else " (n.s.)"
    return f"{fmt(r['diff'], d)} [{fmt(r.ci_lo, d)}, {fmt(r.ci_hi, d)}]{sig}"


# (a, b) pairs reported as "b − a" columns, when both modes are in the data
CONTRASTS = (("centralized", "decentralized"), ("centralized", "hybrid"), ("decentralized", "hybrid"))


def contrasts_in(df):
    ms = set(modes_in(df))
    return [(a, b) for a, b in CONTRASTS if a in ms and b in ms]


def table(df, x, y, xlabel, unit="", d=1, row_label=None):
    ms, cs = modes_in(df), contrasts_in(df)
    head = [xlabel] + [LABELS[m] for m in ms] + [f"{SHORT[b]} − {SHORT[a]} (95% CI)" for a, b in cs]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    ps = [paired(df, x, y, a, b).set_index(x) for a, b in cs]
    stats_ = df.groupby([x, "mode"])[y].agg(["mean", "std"])
    for v in sorted(df[x].unique()):
        label = row_label if row_label is not None else f"{v:g}{unit}"
        cells = [label] + [f"{fmt(stats_.loc[(v, m), 'mean'], d)} ± {fmt(stats_.loc[(v, m), 'std'], d)}" for m in ms]
        cells += [_diff_cell(p.loc[v], d) for p in ps]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


E1_METRICS = [
    ("urg_resp_mean", "Mean response, A0+A1 (min)"), ("urg_resp_p90", "p90 response, A0+A1 (min)"),
    ("urg_resp_p95", "p95 response, A0+A1 (min)"), ("urg_within15_pct", "A0+A1 within 15 min (%)"),
    ("a2_within30_pct", "A2 within 30 min (%)"), ("win_unserved", "Unserved calls (count)"),
    ("urg_fairness_gap", "Rural − urban mean response (min)"), ("urg_gini", "Gini of response times"),
    ("urg_resp_var", "Variance of response (min²)"), ("utilization_pct", "Ambulance utilization (%)"),
    ("diversions", "Hospital diversions (count)"), ("win_offload_rate_pct", "Offload rate (% of arrivals)"),
    ("win_offload_median", "Offload median (min)"), ("msgs_total", "Messages sent"),
    ("bids_per_incident", "Bids per incident"), ("urg_wait_assign_mean", "Call → unit assigned (min)"),
    ("urg_wait_operator_mean", "Wait for a free operator, A0+A1 (min)"),
    ("max_call_queue", "Longest operator queue (calls)"),
]


def _paired_cell(a, b, d=1):
    diff = (b - a).dropna()
    half = stats.t.ppf(0.975, len(diff) - 1) * diff.std(ddof=1) / np.sqrt(len(diff))
    sig = "" if (diff.mean() - half > 0 or diff.mean() + half < 0) else " (n.s.)"
    return f"{fmt(diff.mean(), d)} [{fmt(diff.mean() - half, d)}, {fmt(diff.mean() + half, d)}]{sig}"


def e4_switch_table(d):
    """Switchover delay: H per delay, paired against A, B, and H with an instant switch."""
    s = d[d.experiment == "E4-switch"]
    if s.empty:
        return []
    y = "ev_urg_resp_p95"
    A = s[s["mode"] == "centralized"].set_index("seed")
    B = s[s["mode"] == "decentralized"].set_index("seed")
    H = s[s["mode"] == "hybrid"]
    H0 = H[H.swept_value == H.swept_value.min()].set_index("seed")
    L = ["", f"## E4-switch — Hybrid switchover delay ({s.outage_len.iloc[0]:g}-min outage, "
         f"{s.load.iloc[0]:g}× demand)", "",
         "p95 and mean of A0+A1 calls created during the outage + 60 min. Paired on seeds.", "",
         "| Mode | Delay (min) | p95 (min) | Mean (min) | Unserved (%) | p95 H − A (95% CI) "
         "| p95 H − B (95% CI) | p95 vs instant switch (95% CI) |", "|---|---|---|---|---|---|---|---|"]
    for name, g in (("A, no fallback", A), ("B, no dispatcher", B)):
        L.append(f"| {name} | – | {fmt(g[y].mean())} ± {fmt(g[y].std())} | {fmt(g.ev_urg_resp_mean.mean())} | "
                 f"{fmt(g.win_unserved_pct.mean(), 2)} | – | – | – |")
    for v, g in H.groupby("swept_value"):
        g = g.set_index("seed")
        vs0 = "–" if v == H0.swept_value.iloc[0] else _paired_cell(H0[y], g[y])
        L.append(f"| H | {v:g} | {fmt(g[y].mean())} ± {fmt(g[y].std())} | {fmt(g.ev_urg_resp_mean.mean())} | "
                 f"{fmt(g.win_unserved_pct.mean(), 2)} | {_paired_cell(A[y], g[y])} | {_paired_cell(B[y], g[y])} | {vs0} |")
    return L


def e5_table(d):
    """Bidding window: B per window, paired against A on the same seeds."""
    s = d[d.experiment == "E5"]
    if s.empty:
        return []
    ref = s[s["mode"] == "centralized"].set_index("seed")
    L = ["", "## E5 — Bidding window (normal demand, perfect comms)", "",
         "| Mode | Window (min) | Mean (min) | p95 (min) | Unserved (%) | Messages | p95 B − A (95% CI) |",
         "|---|---|---|---|---|---|---|"]
    L.append(f"| A, no auction | – | {fmt(ref.urg_resp_mean.mean())} ± {fmt(ref.urg_resp_mean.std())} | "
             f"{fmt(ref.urg_resp_p95.mean())} ± {fmt(ref.urg_resp_p95.std())} | "
             f"{fmt(ref.win_unserved_pct.mean())} | {ref.msgs_total.mean():,.0f} | – |")
    for win, g in s[s["mode"] == "decentralized"].groupby("swept_value"):
        g = g.set_index("seed")
        diff = (g["urg_resp_p95"] - ref["urg_resp_p95"]).dropna()
        half = stats.t.ppf(0.975, len(diff) - 1) * diff.std(ddof=1) / np.sqrt(len(diff))
        L.append(f"| B | {win:g} | {fmt(g.urg_resp_mean.mean())} ± {fmt(g.urg_resp_mean.std())} | "
                 f"{fmt(g.urg_resp_p95.mean())} ± {fmt(g.urg_resp_p95.std())} | "
                 f"{fmt(g.win_unserved_pct.mean())} | {g.msgs_total.mean():,.0f} | "
                 f"{fmt(diff.mean())} [{fmt(diff.mean() - half)}, {fmt(diff.mean() + half)}] |")
    return L


def e6_table(d, high):
    """Operators: centralized with N operators minus centralized with unlimited, paired on seeds."""
    s = d[(d.experiment == "E6") & (d["mode"] == "centralized")]
    if s.empty:
        return []
    unl = s.swept_value.max()
    L = ["", "## E6 — Operators: centralized with N operators vs unlimited operators", "",
         f"Paired on seeds against A with unlimited operators ({unl:g} = more than are ever busy at once).", "",
         "| load | operators | p95 A0+A1 (min) | p95 − unlimited (95% CI) | mean wait for operator (min) "
         "| p95 wait for operator, all calls (min) | longest queue |", "|---|---|---|---|---|---|---|"]
    for load in (1.0, high):
        sub = s[s.load == load]
        ref = sub[sub.swept_value == unl].set_index("seed")["urg_resp_p95"]
        for n, g in sub.groupby("swept_value"):
            g = g.set_index("seed")
            diff = (g["urg_resp_p95"] - ref).dropna()
            half = stats.t.ppf(0.975, len(diff) - 1) * diff.std(ddof=1) / np.sqrt(len(diff))
            sig = "" if (diff.mean() - half > 0 or diff.mean() + half < 0) else " (n.s.)"
            if n != unl and (diff == 0).all():
                cell = "0 (identical runs)"
            else:
                cell = "–" if n == unl else f"{fmt(diff.mean(), 2)} [{fmt(diff.mean() - half, 2)}, {fmt(diff.mean() + half, 2)}]{sig}"
            L.append(f"| {load:g}× | {'unlimited' if n == unl else f'{n:g}'} | "
                     f"{fmt(g.urg_resp_p95.mean())} ± {fmt(g.urg_resp_p95.std())} | {cell} | "
                     f"{fmt(g.urg_wait_operator_mean.mean(), 2)} | {fmt(g.all_wait_operator_p95.mean(), 1)} | "
                     f"{fmt(g.max_call_queue.mean(), 1)} |")
    return L


def summary_md(d, high):
    e1 = d[d.experiment == "E1"].assign(k=0)
    n_seeds = e1.seed.nunique()
    ops = d[d.experiment == "E1"].n_operators.iloc[0]
    L = ["# Experiment results — all tables", "",
         "All response times run from the 112 call and include 2 min of simulated call processing for",
         f"both modes (`DISPATCH_HANDLING_MIN`). In A that processing needs a free operator ({ops:g} on shift,",
         "`N_DISPATCH_OPERATORS`), so calls can queue; in B it runs in parallel. Both modes serve the most",
         "urgent calls first. These results supersede all earlier ones. Plain-language reading:",
         "`docs/RESULTS_SUMMARY.md`.", "",
         f"Generated by `experiments/analyze.py` from `{IN_CSV}` ({len(d)} runs, {n_seeds} seeds per setting,",
         f"seeds {d.seed.min()}–{d.seed.max()}). Values are mean ± sd over seeds. Modes: **A** centralized,",
         "**B** decentralized (Contract Net, urgency-ordered). **B − A** is the paired difference on identical",
         "incidents with a 95% t-interval; for times, positive = A better. `(n.s.)` = the interval includes 0.",
         f"High load for E3/E4/E6 = **{high:g}× normal** (highest E2 load where centralized still finishes ≥ 95% of calls).",
         "", "## E1 — Baseline (normal demand, perfect comms)", ""]
    for i, (col, name) in enumerate(E1_METRICS):
        rows = table(e1, "k", col, "Metric", d=2, row_label=name)
        L += rows if i == 0 else rows[2:]

    sections = [
        ("E2 — Demand sweep: p95 A0+A1 (min)", "E2", "load", "urg_resp_p95", "load", "×", None),
        ("E2 — Demand sweep: % unserved", "E2", "load", "win_unserved_pct", "load", "×", None),
        ("E2 — Demand sweep: p95 A2 (min)", "E2", "load", "a2_resp_p95", "load", "×", None),
        ("E2 — Demand sweep: wait for a free operator, A0+A1 (min)", "E2", "load", "urg_wait_operator_mean",
         "load", "×", None),
    ]
    for load in (1.0, high):
        sections += [
            (f"E3 — Message loss at {load:g}×: p95 A0+A1 (min)", "E3-loss", "loss_prob", "urg_resp_p95", "loss", "", load),
            (f"E3 — Message loss at {load:g}×: % unserved", "E3-loss", "loss_prob", "win_unserved_pct", "loss", "", load),
            (f"E3 — Message delay at {load:g}×: p95 A0+A1 (min)", "E3-delay", "delay_ticks", "urg_resp_p95", "delay", " min", load),
        ]
    sections += [
        (f"E4 — Dispatcher outage at {high:g}×: % unserved", "E4",
         "outage_len", "win_unserved_pct", "outage", " min", high),
        (f"E4 — Dispatcher outage at {high:g}×: p95 of calls created during outage + 60 min", "E4",
         "outage_len", "ev_urg_resp_p95", "outage", " min", high),
        (f"E4 — Dispatcher outage at {high:g}×: mean response of calls created during outage + 60 min",
         "E4", "outage_len", "ev_urg_resp_mean", "outage", " min", high),
        (f"E4 — Dispatcher outage at {high:g}×: p95 over the whole day", "E4",
         "outage_len", "urg_resp_p95", "outage", " min", high),
    ]
    for load in (1.0, high):
        sections += [
            (f"E6 — Operators at {load:g}×: p95 A0+A1 (min)", "E6", "n_operators", "urg_resp_p95", "operators", "", load),
            (f"E6 — Operators at {load:g}×: mean A0+A1 (min)", "E6", "n_operators", "urg_resp_mean", "operators", "", load),
        ]
    cs = contrasts_in(d)
    L += ["", "## Crossovers at a glance", "",
          "H (hybrid) runs in E4 only; `–` = that pair was not run in this sweep.", "",
          "| Sweep | Metric | " + " | ".join(f"{SHORT[b]} vs {SHORT[a]}" for a, b in cs) + " |",
          "|---|---|" + "---|" * len(cs)]
    crossings = []
    for title, exp, x, y, xl, unit, load, *hb in sections:
        sub = d[d.experiment == exp]
        if load is not None:
            sub = sub[sub.load == load]
        crossings.append((title, sub, x, y, xl, unit))
        here = contrasts_in(sub)
        verdicts = [crossover_text(paired(sub, x, y, a, b), x, unit, higher_better=bool(hb), a=a, b=b)
                    if (a, b) in here else "–" for a, b in cs]
        L.append(f"| {title.split(':')[0]} | {title.split(':')[1].strip() if ':' in title else y} | "
                 + " | ".join(verdicts) + " |")
    for title, sub, x, y, xl, unit in crossings:
        L += ["", f"## {title}", ""] + table(sub, x, y, xl, unit)
    L += e4_switch_table(d)
    L += e5_table(d)
    L += e6_table(d, high)
    L += ["", "## Figures", ""]
    for f in sorted(os.listdir(FIG_DIR)):
        L.append(f"* `figures/{f}`")
    open(OUT_MD, "w").write("\n".join(L) + "\n")


def main():
    d = pd.read_csv(IN_CSV)
    high = float(open("results/high_load.txt").read().strip())
    figures(d, high)
    summary_md(d, high)
    os.makedirs(PRESENT_DIR, exist_ok=True)
    for f in PRESENTATION:
        shutil.copy(os.path.join(FIG_DIR, f), os.path.join(PRESENT_DIR, f))
    print(f"wrote {OUT_MD}, figures in {FIG_DIR}/ and the presentation pack in {PRESENT_DIR}/")


if __name__ == "__main__":
    main()
