"""
app.py — Local Solara web app for watching the simulation.

Run:  solara run app.py   (then open the printed URL and press play)

Drawing is done by hand in draw_scene() (Mesa 3.5's built-in agent scatter has a
zorder bug). Posts are large squares; ambulances are circles drawn on top so an
idle unit sits inside its post; incidents are triangles coloured by urgency; a
faint line shows where a moving ambulance is headed.
"""

import math

import solara
from matplotlib.figure import Figure
from mesa.visualization import SolaraViz, Slider
from mesa.visualization.utils import update_counter

import config
from model import EmergencyModel

_STATUS_COLOR = {
    "IDLE": "tab:green",
    "EN_ROUTE": "tab:red",
    "ON_SCENE": "gold",
    "TRANSPORTING": "tab:orange",
    "HANDOVER": "tab:purple",
    "RETURNING": "tab:cyan",
}
_CODE_COLOR = {"A0": "red", "A1": "darkorange", "A2": "gold", "B": "gray"}


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
    ax.set_title(f"Twente EMS ({model.mode})  |  t = {getattr(model, 'clock', 0)} min  |  "
                 f"waiting: {waiting}  done: {done}")


@solara.component
def TwenteSpace(model):
    update_counter.get()   # subscribe to Mesa's step counter so this redraws each tick
    fig = Figure(figsize=(6.5, 6.5))
    ax = fig.subplots()
    draw_scene(model, ax)
    solara.FigureMatplotlib(fig)


@solara.component
def LogPanel(model):
    update_counter.get()   # redraw each tick
    lines = getattr(model, "event_log", [])[-24:]
    text = "\n".join(lines) if lines else "(no events yet)"
    solara.Markdown(f"### Event log (latest)\n```\n{text}\n```")


# Interactive knobs (change, then press Reset to apply).
model_params = {
    "mode": {"type": "Select", "value": "centralized",
             "values": ["centralized", "decentralized"], "label": "Dispatch mode"},
    "n_ambulances": Slider("Ambulances", 12, 4, 24, 1),
    "loss_prob": Slider("Message loss probability", 0.0, 0.0, 0.5, 0.05),
    "delay_ticks": Slider("Message delay (min)", 0, 0, 5, 1),
    "outage_start": Slider("Dispatcher outage start (min)", 0, 0, 200, 10),
    "outage_len": Slider("Dispatcher outage length (min, 0 = off)", 0, 0, 120, 10),
    "seed": Slider("Random seed", 42, 1, 100, 1),
}

model = EmergencyModel()
page = SolaraViz(model, components=[TwenteSpace, LogPanel],
                 model_params=model_params, name="Twente EMS")
page  # noqa: B018