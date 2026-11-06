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

## Main findings

Each setting ran on 30 simulated days. p95 is the response time of the slowest 5% of urgent (A0+A1) calls,
measured from the 112 call. Outage results are at 1.25× normal demand.

| Situation | Centralized | Auction | Hybrid |
|---|---|---|---|
| Normal day, p95 | **17.5 min** | 19.6 min | same as centralized |
| 2× demand, p95 | **167 min** | 229 min | not tested |
| 50% of messages lost, p95 | **19.3 min** | 39.7 min | not tested |
| 60-min control-room outage, p95 (calls during it and the hour after) | 48.9 min | 27.1 min | **26.7 min** |
| Messages per day, normal demand | **119** | 1,355 | not tested |

The hybrid's outage result assumes an instant switch, and that crews can still exchange messages and
112 calls still get in. The model uses an abstract map and idealised operators, so these are model
results, not predictions for the real region. See the
[limitations](docs/RESULTS_SUMMARY.md#main-limitations).

## Key figures

Blue is centralized (A), purple is the auction (B) and green is the hybrid (H). Lines are the mean over
30 days, shaded bands are the middle 50% of days, and the dashed line is the 15-minute norm.

**Control-room outage: the one case where the auction wins.** Centralized calls pile up while the
dispatcher is down, and the auction has no central point to lose. The hybrid matches centralized when
nothing fails and matches the auction during an outage. Unserved calls barely differ.

![p95 response and unserved calls against outage length for the three modes](results/presentation/E4_outage_p95.png)

**Switchover delay: how fast the fallback must start.** For a 1-hour outage, switching within 10 min
keeps all of the gain, 30 min keeps about 70% and 50 min about a quarter. A switch that comes only once the
control room is back is slightly worse than no fallback.

![Hybrid response time against switchover delay for a 60-minute outage](results/presentation/E4_switchover_delay.png)

**Rising demand: hospitals become the limit.** Centralized is faster for urgent calls at every demand
level. From about 1.5× demand the emergency departments are full, and both modes leave the same share of
calls unserved.

![p95 response and unserved calls against demand](results/presentation/E2_load_p95_unserved.png)

**Message loss: the auction needs good communication.** It uses three messages per call (announce, bid,
award) where the dispatcher uses one, so its p95 roughly doubles at 50% loss.

![p95 response and unserved calls against message loss at 1× and 1.25× demand](results/presentation/E3_message_loss.png)

**Bidding window: the auction's everyday cost.** The mean penalty equals the window, minute for minute. A
zero window never works, because the auction closes before any bid arrives.

![Mean and p95 response against bidding window length](results/presentation/E5_bid_window.png)

**Operators: staffing is not the bottleneck.** One operator performs about the same as unlimited operators.
Even at 5× demand, urgent calls wait about 1 min for an operator, against hundreds of minutes for an
ambulance. The operators are idealised, so this is a best case for the control room.

![p95 response against number of operators, and where centralized calls wait](results/presentation/E6_operators.png)

## Where to read

| File | What it is |
|---|---|
| [`docs/RESULTS_SUMMARY.md`](docs/RESULTS_SUMMARY.md) | The findings in plain language, one pass |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Every modelling decision and why (calibration, call processing, bidding window, metrics) |
| [`docs/REFERENCES.md`](docs/REFERENCES.md) | Every source, with what it was used for |
| [`results/presentation/`](results/presentation/) | The six figures worth showing, with a note on each |
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
