# Twente ambulance dispatch — centralized vs decentralized (agent-based model)

A Mesa simulation of urgent ambulance care in RAV Twente: 11 ambulance posts and the two 24/7
emergency departments (MST Enschede, ZGT Almelo). It compares two ways of allocating ambulances
on identical emergencies, both serving the most urgent calls first:

* **Centralized:** a control room with a limited number of operators processes each call and sends the
  nearest free ambulance.
* **Decentralized:** no dispatcher; ambulances bid their arrival time (Contract Net).

These are tested under rising demand, lost or delayed messages, a control-room outage, different
bidding windows and different numbers of operators.

**Short answer:** central dispatch wins in everyday conditions and under load, even with one operator on
shift; an urgency-ordered auction is a plausible backup when the dispatcher is down for half an hour or more.
A hybrid (`mode="hybrid"`: central dispatch, auction only during an outage; tested in E4 only) keeps the
everyday performance and removes most of the outage cost, assuming the switch is noticed quickly. Details: [`docs/RESULTS_SUMMARY.md`](docs/RESULTS_SUMMARY.md).

## Where to read

| File | What it is |
|---|---|
| [`docs/RESULTS_SUMMARY.md`](docs/RESULTS_SUMMARY.md) | The findings in plain language, one pass |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every modelling decision and why (calibration, call processing, bidding window, metrics) |
| [`docs/REFERENCES.md`](docs/REFERENCES.md) | Every source, with what it was used for |
| [`results/presentation/`](results/presentation/) | The five figures worth showing, with a note on each |
| [`results/tables.md`](results/tables.md) | Every number, with 95% confidence intervals |
| [`results/calibration_report.md`](results/calibration_report.md) | How the model was fitted to Dutch data |

## Repository map

```
module/
├── README.md
├── requirements.txt
├── src/            model code: config, model, agents, channel, incidents, metrics, viz, generate_incidents
├── apps/           app.py (Solara experiment app), voice_app.py + run_voice_incident.py (voice-agent incident)
├── experiments/    calibrate.py, run_experiments.py, analyze.py, experiment_core.py
├── data/           incident files for the app (incident.json, incident_sample.json)
├── docs/           RESULTS_SUMMARY.md, DECISIONS.md, REFERENCES.md
└── results/        experiments.csv, e4_timeline.csv, calibration_grid.csv, tables.md,
                    calibration_report.md, figures/, presentation/
```

## Running

Install the dependencies once (Python 3.11+): `pip install -r requirements.txt`. Run everything from
this `module/` directory.

**Watch the simulation**

```bash
solara run apps/app.py                 # experiment app: map, metrics, "compare modes" panel
INCIDENT_FILE=data/incident_sample.json solara run apps/app.py
python src/generate_incidents.py --n 18 --minutes 180 --out data/incident.json   # new incident file
```

**One voice-agent incident** (needs the `../conversational-agent` folder; MongoDB optional)

```bash
python apps/run_voice_incident.py --file ../conversational-agent/examples/sample_incident.json
solara run apps/voice_app.py           # same, in the browser (latest MongoDB incident by default)
```

**Reproduce the study** (about 5 minutes in total on a laptop)

```bash
python experiments/calibrate.py        # ~2 min: fit the [ASSUMPTION] values, write src/config.py
python experiments/run_experiments.py  # ~2 min: E1–E6, 30 simulated days per setting
python experiments/analyze.py          # figures, tables.md and the presentation pack
python experiments/export_incidents.py # results/incidents_report.md + incidents.csv: the calls each experiment used
```

`calibrate.py --dry-run` refits without changing `src/config.py`.
