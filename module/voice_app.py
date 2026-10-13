"""
voice_app.py — Watch one voice-agent incident being resolved, in Solara.

Loads an incident recorded by the conversational agent (MongoDB by default),
shows its payload and how it is mapped into the model, then runs the model on
that incident alone. Same loading path as run_voice_incident.py.

Run:
  solara run voice_app.py                                  # latest incident in MongoDB
  INCIDENT_ID=INC-DD9ADB398988 solara run voice_app.py     # a specific one
  VOICE_FILE=../conversational-agent/examples/sample_incident.json solara run voice_app.py
  VOICE_LATLON=52.2393,6.8555 solara run voice_app.py      # override the location lookup

MONGODB_URI is read as in the CLI. Switch the dispatch mode in the sidebar and
press Reset to replay the same incident under the other condition.
"""

import json
import os

import solara
from matplotlib.figure import Figure
from mesa.visualization import SolaraViz, Slider
from mesa.visualization.utils import update_counter

import config
from incidents import to_operational_code
from run_voice_incident import (
    TrackedModel, VoiceIncidentError, _fmt, check_simulable, from_file, from_mongo, prepare, validate,
)
from viz import LogPanel, draw_scene


def _load():
    """Return (raw record, prepared record, error message). Errors are shown on the page."""
    record = None
    try:
        incident_id = os.environ.get("INCIDENT_ID")
        if os.environ.get("VOICE_FILE"):
            record = from_file(os.environ["VOICE_FILE"], incident_id)
        else:
            record = from_mongo(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"), incident_id)
        validate(record)
        latlon = os.environ.get("VOICE_LATLON")
        voice = prepare(record, tuple(float(v) for v in latlon.split(",")) if latlon else None)
        check_simulable(voice)
        return record, voice, None
    except VoiceIncidentError as e:
        return record, None, str(e)
    except Exception as e:  # Mongo unreachable, schema violation, bad VOICE_LATLON, ...
        return record, None, f"{type(e).__name__}: {e}"


RECORD, VOICE, ERROR = _load()


@solara.component
def PayloadPanel(model):
    if ERROR:
        solara.Error(ERROR)
    if RECORD is None:
        return
    lines = [f"### Voice incident {RECORD.get('incident_id', '?')}"]
    if VOICE is not None:
        loc = VOICE["location"]
        primary = VOICE["patients"]["primary_patient"]
        x, y = config.latlon_to_xy(loc["latitude"], loc["longitude"])
        code = to_operational_code(VOICE["incident"]["severity"], primary["breathing"])
        n_patients = VOICE["patients"]["count"] or 1
        lines += [
            "| | |", "|---|---|",
            f"| Caller said | {loc.get('raw_text') or '-'} |",
            f"| Coordinates | {loc['latitude']:.4f}, {loc['longitude']:.4f} |",
            f"| Grid position | ({x:.1f}, {y:.1f}) km |",
            f"| Severity, breathing | {VOICE['incident']['severity']}, {primary['breathing']} |",
            f"| Operational code | **{code}** |",
            f"| Patients | {n_patients} |",
        ]
        if n_patients > 1:
            lines.append("\n*The model sends ONE ambulance per incident; extra patients are not simulated yet.*")
    lines.append(f"\n#### Payload\n```json\n{json.dumps(RECORD, indent=2, default=str)}\n```")
    solara.Markdown("\n".join(lines))


@solara.component
def VoiceMap(model):
    update_counter.get()
    fig = Figure(figsize=(6.5, 6.5))
    ax = fig.subplots()
    draw_scene(model, ax)
    inc = getattr(model, "tracked", None)
    if inc is not None:
        # The voice incident stays marked after it is reached; its unit gets a ring.
        ax.scatter(*inc.pos, marker="*", s=380, facecolor="none", edgecolor="black",
                   linewidths=1.2, zorder=6)
        ax.annotate(inc.incident_id, inc.pos, fontsize=7, fontweight="bold",
                    xytext=(8, -12), textcoords="offset points")
    amb = getattr(model, "tracked_amb", None)
    if amb is not None:
        ax.scatter(*amb.pos, s=260, facecolor="none", edgecolor="black",
                   linewidths=1.5, zorder=6)
    solara.FigureMatplotlib(fig)


@solara.component
def ResultCard(model):
    update_counter.get()
    if getattr(model, "tracked", None) is None:
        solara.Markdown("### Outcome\n(no voice incident loaded)")
        return
    r = model.summary()
    status = "closed" if r["closed_after"] is not None else f"in progress (t = {model.clock} min)"
    rows = [
        ("Status", status),
        ("Operational code", r["code"]),
        ("Unit assigned after", _fmt(r["assigned_after"], " min")),
        ("Response time", _fmt(r["response"], " min")),
        ("Ambulance", r["unit"]),
        ("Hospital", r["transport"]),
        ("Offload delay", _fmt(r["offload"], " min")),
        ("Closed after", _fmt(r["closed_after"], " min")),
        ("Messages sent", _fmt(r["metrics"].get("msgs_total"))),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    solara.Markdown(f"### Outcome ({model.mode})\n| | |\n|---|---|\n{body}")


model_params = {
    "incidents": [VOICE] if VOICE is not None else [],   # fixed: the voice incident only
    "mode": {"type": "Select", "value": "centralized",
             "values": ["centralized", "decentralized"], "label": "Dispatch mode"},
    "n_ambulances": Slider("Ambulances", 12, 4, 24, 1),
    "loss_prob": Slider("Message loss probability", 0.0, 0.0, 0.5, 0.05),
    "delay_ticks": Slider("Message delay (min)", 0, 0, 5, 1),
    "seed": Slider("Random seed", config.SEED, 1, 100, 1),
}

model = TrackedModel(incidents=model_params["incidents"], mode="centralized")
page = SolaraViz(model, components=[PayloadPanel, VoiceMap, ResultCard, LogPanel],
                 model_params=model_params, name="Twente EMS: voice incident")
page  # noqa: B018
