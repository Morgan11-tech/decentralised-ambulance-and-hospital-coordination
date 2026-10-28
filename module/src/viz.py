"""
viz.py — Solara components shared by app.py and voice_app.py.

Drawing is done by hand in draw_scene() (Mesa 3.5's built-in agent scatter has a
zorder bug). Posts are large squares; ambulances are circles drawn on top so an
idle unit sits inside its post; incidents are triangles coloured by urgency; a
faint line shows where a moving ambulance is headed.
"""

import math

import solara
from matplotlib.figure import Figure
from mesa.visualization.utils import update_counter

import config

_STATUS_COLOR = {
    "IDLE": "tab:green",
    "EN_ROUTE": "tab:red",
    "ON_SCENE": "gold",
    "TO_HOSPITAL": "tab:orange",
    "WAITING": "black",
    "HANDOVER": "tab:purple",
    "RETURNING": "tab:cyan",
}
_CODE_COLOR = {"A0": "red", "A1": "darkorange", "A2": "gold", "B": "gray"}


def mode_label(model):
    """Mode name; for the hybrid also which allocation is running this tick."""
    if model.mode != "hybrid":
        return model.mode
    if model._self_dispatch_active():
        return "hybrid: units bidding"
    if not model._dispatcher_up():
        return "hybrid: outage not yet noticed"
    return "hybrid: dispatcher"


def draw_scene(model, ax):
    # Ambulance posts: large light squares (so a parked ambulance sits inside).
    for name, (x, y) in config.POSTS_XY.items():
        ax.scatter(x, y, marker="s", s=320, facecolor="#dCE6F7",
                   edgecolor="tab:blue", linewidths=1.0, zorder=1)
        ax.annotate(name, (x, y), fontsize=6, xytext=(6, 6), textcoords="offset points")

    # Hospitals: purple crosses (red when on diversion); label shows load/capacity.
    for h in getattr(model, "hospital_agents", []):
        x, y = h.home_pos
        color = "red" if h.on_diversion else "tab:purple"
        ax.scatter(x, y, marker="P", color=color, s=220, zorder=2)
        tag = f"{h.name} {h.load}/{h.capacity}" + (" DIVERT" if h.on_diversion else "")
        ax.annotate(tag, (x, y), fontsize=7, xytext=(6, 6), textcoords="offset points")

    # Incidents still to be reached: waiting (unassigned) + en-route targets.
    to_draw = list(getattr(model, "active_incidents", []))
    for a in getattr(model, "ambulances", []):
        if a.status == "EN_ROUTE" and a.current_incident is not None:
            to_draw.append(a.current_incident)
    for inc in to_draw:
        x, y = inc.pos
        ax.scatter(x, y, marker="^", color=_CODE_COLOR.get(inc.code, "black"),
                   s=90, zorder=4, edgecolors="black", linewidths=0.6)

    # Ambulances: circles on top, coloured by status; faint line to target if moving.
    for a in getattr(model, "ambulances", []):
        x, y = a.pos
        if a.target is not None and a.status in ("EN_ROUTE", "TRANSPORTING", "RETURNING"):
            ax.plot([x, a.target[0]], [y, a.target[1]], color="gray",
                    lw=0.6, ls="--", alpha=0.4, zorder=2)
        ax.scatter(x, y, color=_STATUS_COLOR.get(a.status, "tab:gray"),
                   s=70, zorder=5, edgecolors="black", linewidths=0.8)

    ax.set_xlim(0, config.SPACE_WIDTH_KM)
    ax.set_ylim(0, config.SPACE_HEIGHT_KM)
    ax.set_aspect("equal")
    ax.set_xlabel("km")
    ax.set_ylabel("km")
    waiting = len(getattr(model, "active_incidents", []))
    done = len(getattr(model, "completed", []))
    ax.set_title(f"Twente EMS ({mode_label(model)})  |  t = {getattr(model, 'clock', 0)} min  |  "
                 f"waiting: {waiting}  done: {done}")


@solara.component
def TwenteSpace(model):
    update_counter.get()   # subscribe to Mesa's step counter so this redraws each tick
    fig = Figure(figsize=(6.5, 6.5))
    ax = fig.subplots()
    draw_scene(model, ax)
    solara.FigureMatplotlib(fig)


def _fmt(v):
    try:
        return f"{v:.1f}" if isinstance(v, float) else str(v)
    except Exception:
        return str(v)


@solara.component
def MetricsPanel(model):
    update_counter.get()
    m = getattr(model, "metrics", {}) or {}
    if not m:
        solara.Markdown("### Metrics\n(run the model to populate)")
        return
    rows = [
        ("Completed / total", f"{m.get('completed',0)} / {m.get('total',0)}"),
        ("Unserved", m.get("unserved", 0)),
        ("Response mean (min)", _fmt(m.get("resp_mean"))),
        ("Response p95 (min)", _fmt(m.get("resp_p95"))),
        ("Within 15 min", f"{_fmt(m.get('within15_pct'))}%"),
        ("Fairness gap rural-urban (min)", _fmt(m.get("fairness_gap"))),
        ("Gini (response times)", _fmt(m.get("gini"))),
        ("Utilization", f"{_fmt(m.get('utilization_pct'))}%"),
        ("Hospital diversions", m.get("diversions", 0)),
        ("Offload events", m.get("offload_events", 0)),
        ("Messages sent", m.get("msgs_total", 0)),
        ("Bids per incident", _fmt(m.get("bids_per_incident"))),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    solara.Markdown(f"### Metrics ({model.mode})\n| metric | value |\n|---|---|\n{body}")


@solara.component
def MetricsChart(model):
    update_counter.get()
    fig = Figure(figsize=(6.5, 3.2))
    ax = fig.subplots()
    df = model.datacollector.get_model_vars_dataframe() if hasattr(model, "datacollector") else None
    if df is not None and len(df) > 1:
        ax.plot(df.index, df["resp_p95"], color="tab:red", lw=1.5, label="response p95 (min)")
        ax.plot(df.index, df["within15_pct"], color="tab:green", lw=1.2, label="within 15 min (%)")
        ax.axhline(15, color="gray", ls="--", lw=0.8, alpha=0.6)   # the 15-min norm
        ax.plot(df.index, df["utilization_pct"], color="tab:blue", lw=1.0,
                alpha=0.7, label="utilization (%)")
        ax.set_xlabel("time (min)")
        ax.legend(fontsize=7, loc="upper right")
        ax.set_title("Metrics over time")
    else:
        ax.text(0.5, 0.5, "metrics will appear as the model runs",
                ha="center", va="center", fontsize=9)
        ax.axis("off")
    solara.FigureMatplotlib(fig)


@solara.component
def LogPanel(model):
    update_counter.get()   # redraw each tick
    lines = getattr(model, "event_log", [])[-24:]
    text = "\n".join(lines) if lines else "(no events yet)"
    solara.Markdown(f"### Event log (latest)\n```\n{text}\n```")
