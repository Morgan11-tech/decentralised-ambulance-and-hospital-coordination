"""
app.py — Local Solara web app for watching the simulation.

Run:  solara run app.py   (then open the printed URL and press play)

The map and panels live in viz.py (shared with voice_app.py). The CompareModes
panel below is specific to the experiment page: it is HIDDEN behind a button and,
when opened, runs BOTH dispatch modes on the identical incidents and settings so
you can compare them without switching mode.
"""

import solara
from matplotlib.figure import Figure
from mesa.visualization import SolaraViz, Slider

import metrics
from model import EmergencyModel
from viz import LogPanel, MetricsChart, MetricsPanel, TwenteSpace


def _fmt(v):
    try:
        return f"{v:.1f}" if isinstance(v, float) else str(v)
    except Exception:
        return str(v)


def _run_to_end(mode, kwargs, cap=20000):
    """Build one model in the given mode and run it to completion (or the cap)."""
    m = EmergencyModel(mode=mode, **kwargs)
    guard = 0
    while guard < cap:
        done = (len(m.completed) == len(m.incidents)
                and all(a.status == "IDLE" for a in m.ambulances))
        if done:
            break
        m.step()
        guard += 1
    return metrics.summary(m), m.datacollector.get_model_vars_dataframe()


@solara.component
def CompareModes(model):
    """Collapsible panel: on demand, run BOTH modes on the identical incidents and
    settings and show them together. Hidden by default (does no work until opened),
    and cached so it only recomputes when a knob changes, not every tick.
    """
    show = solara.use_reactive(False)
    kwargs = dict(getattr(model, "_build_kwargs", {}))
    key = tuple(sorted((k, str(v)) for k, v in kwargs.items()))

    def both():
        if not show.value:
            return None                      # do nothing while collapsed
        return {m: _run_to_end(m, kwargs) for m in ("centralized", "decentralized")}

    results = solara.use_memo(both, [key, show.value])

    solara.Button(
        label=("Hide comparison" if show.value else "Compare both modes"),
        on_click=lambda: show.set(not show.value),
        outlined=True,
    )
    if not show.value or results is None:
        return

    cent_s, cent_df = results["centralized"]
    dec_s, dec_df = results["decentralized"]

    fig = Figure(figsize=(6.0, 5.2))
    ax1, ax2 = fig.subplots(2, 1)

    # (1) response p95 over time, both modes
    ax1.plot(cent_df.index, cent_df["resp_p95"], color="tab:blue", lw=1.6, label="centralized")
    ax1.plot(dec_df.index, dec_df["resp_p95"], color="tab:purple", lw=1.6, label="decentralized")
    ax1.axhline(15, color="gray", ls="--", lw=0.8, alpha=0.6)   # the 15-min norm
    ax1.set_xlabel("time (min)")
    ax1.set_ylabel("response p95 (min)")
    ax1.legend(fontsize=7)
    ax1.set_title("Response p95 over time — both modes")

    # (2) final response times, grouped bars (same unit: minutes)
    labels = ["p95 (min)", "mean (min)"]
    cent_vals = [cent_s.get("resp_p95", float("nan")), cent_s.get("resp_mean", float("nan"))]
    dec_vals = [dec_s.get("resp_p95", float("nan")), dec_s.get("resp_mean", float("nan"))]
    x = range(len(labels))
    ax2.bar([i - 0.18 for i in x], cent_vals, 0.36, color="tab:blue", label="centralized")
    ax2.bar([i + 0.18 for i in x], dec_vals, 0.36, color="tab:purple", label="decentralized")
    ax2.set_xticks(list(x))
    ax2.set_xticklabels(labels)
    ax2.legend(fontsize=7)
    ax2.set_title("Final response times")
    fig.tight_layout()
    solara.FigureMatplotlib(fig)

    # compact side-by-side table of the headline numbers
    def row(label, key_, pct=False):
        cv, dv = cent_s.get(key_, float("nan")), dec_s.get(key_, float("nan"))
        suf = "%" if pct else ""
        return f"| {label} | {_fmt(cv)}{suf} | {_fmt(dv)}{suf} |"
    table = "\n".join([
        row("Response p95 (min)", "resp_p95"),
        row("Response mean (min)", "resp_mean"),
        row("Within 15 min", "within15_pct", pct=True),
        row("Unserved", "unserved"),
        row("Fairness gap (min)", "fairness_gap"),
        row("Gini", "gini"),
        row("Bids per incident", "bids_per_incident"),
    ])
    solara.Markdown(
        "#### Compare modes (same incidents & settings)\n"
        "| metric | centralized | decentralized |\n|---|---|---|\n" + table
    )


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
# Order: map, then metrics-over-time beside it, then the collapsible comparison,
# then the live metrics table and the log.
page = SolaraViz(model,
                 components=[TwenteSpace, MetricsChart, CompareModes, MetricsPanel, LogPanel],
                 model_params=model_params, name="Twente EMS")
page  # noqa: B018