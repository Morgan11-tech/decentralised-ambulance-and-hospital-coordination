# Results summary

*Plain-language findings from the Twente ambulance model. Figures are in `results/figures/`;
every number below, with its 95% confidence interval, is in `results/tables.md`. Why the model is
built the way it is: `DECISIONS.md`. Sources: `REFERENCES.md`.*

**These results supersede all earlier versions** (re-run on 2026-10-28). What changed:

- The centralized control room now has a **finite number of operators** (1 on shift by default), so
  calls can queue for one.
- **Both modes now serve the most urgent calls first.** The plain auction and the priority on/off
  comparison are gone.
- The experiment set was trimmed to six experiments.
- **E4 now also runs a fallback hybrid (H)**: centralized normally, auction only while the control
  room is down. It is tested in E4 only, where it is the only place it can differ from centralized.
- **Clock fix and re-calibration.** The model's clock used to start at each day's *first* call, which
  left the last minutes of the measured day without new calls (on average 15 min at normal demand). It
  now starts with the generated day. Calibration was re-run and chose ZGT Almelo 6 ED places (was 7) and
  a 195-min ED stay (was 210); fleet and speed are unchanged. Every experiment was re-run.
  Details of the incident streams: `results/incidents_report.md`.

All response times run from the 112 call and include 2 minutes of call processing in both modes.

---

## The answer in one paragraph

In this model, **central dispatch is better in everyday conditions and under heavy demand, and it is
far less sensitive to bad communication.** Giving the control room realistic, finite staffing does
not change that. With the call volumes of Twente, even one operator is almost never the bottleneck;
the ambulances are. The auction **wins in one situation: when the control room is down for half an hour
or more.** So the model supports central dispatch as the everyday system and an urgency-ordered
auction as a possible **backup** for a dispatcher failure. It does not support replacing the dispatcher.
Tested directly, that backup (the **hybrid**) gets the best of both: it is identical to central
dispatch when nothing fails, and as good as the auction during an outage (assuming the switch to bidding
is instant). **How fast the switch happens decides most of its value:** for a 1-hour outage, switching
within 10 minutes keeps all the gain, after 20 minutes about 90% is left, after 30 minutes about 70%,
after 50 minutes about a quarter, and a switch that comes only when the control room is already back is
slightly worse than no fallback at all.

---

## The two modes compared

* **A — Centralized.** A control room processes each call (operators on shift: 1 by default; when busy,
  calls queue, most urgent first), then sends the nearest free ambulance, most urgent call first
  (current Dutch practice).
* **B — Decentralized.** No dispatcher. Each call is announced, free ambulances bid their arrival time,
  and after a 2-minute bidding window the fastest bid wins (Contract Net, Smith 1980). Calls are
  auctioned most urgent first.

**The one deliberate asymmetry:** both modes pay the same 2 minutes of call processing, but only A
needs a shared operator for it. B processes every call in parallel. That is what "having a central
control room" means here (`DECISIONS.md` §4b).

Both modes get **identical emergencies** on each of 30 simulated days, so differences come from the
dispatch method, not from luck.

---

## Headline numbers per experiment

**E1 — Normal day in Twente** (`E2_load_p95_unserved.png`, at 1×)

* Centralized stays realistic: p95 **17.5 min** (real Dutch regions: 15:08–18:20; on the calibration
  days 16.1 min, inside the 15–17 target band). 90% of urgent calls arrive within 15 min.
* The auction is about 2 min slower at p95 (**19.6 min**; 84% within 15 min).
* Calls wait on average 0.1 min for a free operator, and the longest queue in a day is 1–2 calls.
* The auction sends about 11 times as many messages (1,355 vs 119 per day).

**E2 — Rising demand, 1× to 5×** (`E2_load_p95_unserved.png`, `E2_load_urgent_vs_A2.png`)

* Centralized is better for urgent calls at **every** demand level (p95 at 1.5×: 76 min A vs 90 min B;
  at 2×: 167 vs 229 min).
* With both modes urgency-aware, the gap under load is far smaller than with the old plain auction
  (which reached 203 min at 1.5×), but it does not close.
* Less urgent (A2) calls: centralized is as good or better at every level.
* Above about 1.5× demand the two emergency departments are full, and both modes leave the same share
  of calls unserved. From then on, hospitals, not dispatch, limit the system.

**E3 — Lost or delayed messages** (`E3_message_loss.png`, `E3_message_delay.png`)

* The auction is **much more sensitive**. At normal demand, losing half of all messages moves centralized
  from 17.5 to 19.3 min, but the auction from 19.6 to 39.7 min. A 5-min delay: 23.3 (A) vs 36.9 min (B).
* At 1.25× demand the pattern is the same, only larger (50% loss: 43.3 vs 65.3 min).

**E4 — Control room outage, at 1.25× demand** (`E4_outage_p95.png`, `E4_outage_recovery_timeline.png`)

* For calls made during the outage and the hour after, the auction is clearly better from **30 minutes**
  of outage (p95 25 vs 30 min; at 60 min 27 vs 49 min; at 120 min 30 vs 96 min). At 0 and 15 min there is
  no clear difference for these calls.
* Over the whole day, the auction is better only for outages of 90 min or longer.
* The auction is unaffected because there is no central point to lose. After the dispatcher comes back,
  its backlog takes about 20 min (60-min outage) to an hour (120-min outage) to clear.

**E4 + hybrid — central dispatch with an auction as fallback** (`E4_outage_p95.png`,
`E4_outage_recovery_timeline.png`, `E4_switchover_delay.png`)

*Hypothesis (stated before the run):* H follows A everywhere except during the outage, where it follows
B, giving a line at or below both. *What the data shows* (p95 of A0+A1 calls made during the outage and
the hour after, paired on 30 days):

| Outage | A | B | H | H − A (95% CI) | H − B (95% CI) |
|---|---|---|---|---|---|
| 0 min | 20.9 | 24.0 | 20.9 | 0 (identical runs) | −3.1 [−6.7, 0.4] n.s. |
| 15 min | 23.3 | 25.0 | 23.3 | −0.1 [−1.0, 0.9] n.s. | −1.8 [−4.9, 1.4] n.s. |
| 30 min | 29.9 | 25.2 | 25.1 | −4.8 [−7.4, −2.2] | −0.1 [−3.1, 2.9] n.s. |
| 60 min | 48.9 | 27.1 | 26.7 | −22.1 [−28.9, −15.4] | −0.4 [−3.6, 2.8] n.s. |
| 90 min | 73.1 | 29.5 | 29.6 | −43.5 [−52.9, −34.1] | +0.2 [−3.3, 3.7] n.s. |
| 120 min | 96.4 | 30.2 | 29.4 | −67.0 [−77.7, −56.2] | −0.7 [−5.6, 4.1] n.s. |

* **The hypothesis holds.** With no outage H is A, run for run. During an outage H is clearly better
  than A from 30 min on, and **level with B** at every outage length (no significant difference). So H
  takes B's resilience during the outage without paying B's everyday cost.
* **Over the whole day** (p95 of all urgent calls), H is better than B at 0–60 min of outage (by 3–5 min:
  the everyday bidding cost B pays the rest of the day) and better than A from 60 min on (by 6 min at
  60, 26 min at 120). It is never significantly worse than either.
* **Mean response** tells the same story (60-min outage: A 26.6, B 16.0, H 16.4 min).
* **The timeline shows the switch working:** H leaves A at outage onset (no backlog spike) and is back on
  A at recovery with nothing to clear.
* **Unserved calls:** no significant difference between any pair at any outage length (all 0.5–0.8%).
* **Cost:** only during the outage, three messages per call instead of one (60-min outage: 203 messages
  per day vs 149 for A and 1,675 for B).
* **Switchover delay** (`E4_switchover_delay.png`, 60-min outage, delay = minutes to notice the outage
  and switch on; the same delay applies to handing back):

  | Delay | H p95 (min) | H − A (95% CI) | H − B (95% CI) | vs instant switch (95% CI) | Gain over A kept |
  |---|---|---|---|---|---|
  | 0 | 26.7 | −22.1 [−28.9, −15.4] | −0.4 n.s. | – | 100% |
  | 2 | 26.0 | −22.9 [−29.4, −16.3] | −1.1 n.s. | −0.7 n.s. | ≈100% |
  | 5 | 26.5 | −22.3 [−29.0, −15.7] | −0.6 n.s. | −0.2 n.s. | ≈100% |
  | 10 | 26.5 | −22.3 [−28.6, −16.0] | −0.6 n.s. | −0.2 n.s. | ≈100% |
  | 20 | 29.2 | −19.7 [−25.8, −13.6] | +2.0 [−0.3, 4.4] n.s. | +2.4 [0.4, 4.5] | 89% |
  | 30 | 32.9 | −16.0 [−21.0, −10.9] | +5.8 [1.7, 9.9] | +6.2 [3.5, 8.8] | 72% |
  | 50 | 43.5 | −5.4 [−6.9, −3.8] | +16.4 [10.4, 22.4] | +16.8 [11.1, 22.4] | 24% |
  | 60 | 51.3 | **+2.4 [1.7, 3.2]** | +24.2 [17.4, 30.9] | +24.6 [18.1, 31.0] | none |

  (A without fallback: 48.9 min; B: 27.1 min.)

  * **Up to 10 min:** no measurable loss. Few urgent calls (about 3 per hour at this demand) arrive in a
    short gap, and the ones that do wait at most the gap.
  * **20 min:** a small but real loss (+2.4 min, about 90% of the gain kept).
  * **From 30 min the gain wears away quickly:** +6.2 min at 30, +16.8 at 50. The gap at the start is
    simply an outage without any fallback, and the pile of waiting calls grows during it.
  * **As good as B only if the switch takes under ~20 min.** From 30 min a pure auction would have done
    clearly better during the outage.
  * **50 min** (roughly how long Twente took to scale up to GRIP 2 in the 2019 112 outage [VRT-2019],
    a different kind of failure, so only a rough reference): about a quarter of the gain left.
  * **60 min, i.e. the switch arrives when the control room is already back:** H is slightly but
    clearly **worse than having no fallback** (+2.4 min). It then bids for an hour while the faster
    dispatcher could have been working. A late switch-on with a late hand-back is not harmless.
  * Unserved calls stay at 0.6–0.7% at every delay.

**E5 — Length of the bidding window** (`E5_bid_window.png`)

* At normal demand, the everyday penalty **equals the window, minute for minute.**

  | Window | Mean penalty vs A | Auction p95 |
  |---|---|---|
  | 1 min | +1.0 min | 18.9 min |
  | 2 min | +1.9 min | 19.6 min |
  | 3 min | +2.8 min | 20.7 min |

  Centralized: p95 17.5 min.
* A 1-min window leaves 1.4 min of p95 penalty. That is the shortest the model's 1-minute time step
  allows.
* A zero window fails: the auction closes before any bid arrives, and no call is ever assigned.

**E6 — How many operators the control room needs** (`E6_operators.png`)

* With **1 operator**, centralized p95 differs from unlimited operators by +0.1 min at normal demand and
  −1.0 min at 1.25×. Neither difference is statistically clear.
* With **2 or more operators** at normal demand (3 or more at 1.25×), the runs are **identical** to
  unlimited: no call ever waits.
* Even at 5× demand with 1 operator, urgent calls wait only about 1 min on average for an operator, out of
  about 590 min on average from the call until an ambulance is assigned. The bottleneck is the fleet and the hospitals, not the
  control room.
* So **centralized's advantage does not depend on generous staffing** in this model. Caveat: the operators
  here are idealised (busy only for the 2-min processing, no after-call work). A real control room queues
  more, so this is a best case for A.

---

## Two weaknesses of the auction, and one strength

| Weakness | When it matters | What it costs | Can it be fixed? |
|---|---|---|---|
| **1. The bidding window** | Every day | Minute for minute the window length (≈ 2 min at p95 with a 2-min window) | Partly: a 1-min window costs 1.4 min at p95. It cannot go below the bid round trip without missing bids (E5). |
| **2. Three messages per call** | Bad communication | p95 roughly doubles at 50% message loss (20 → 40 min) | No, it is built into bidding (announce → bid → award vs one assignment). |

| Strength | When it matters | What it gives |
|---|---|---|
| **No single point of failure** | Control-room outage of ~30 min or more | Response stays near normal while the dispatcher's backlog grows |

The hybrid keeps that strength without paying either weakness on normal days: it bids only while the
dispatcher is down.

The operator queue, the other central bottleneck we added, does **not** turn out to be a weakness of
centralized dispatch at Twente's call volumes (E6).

---

## Why the hybrid copes better with an outage, in plain words

Think of the control room as the **only person allowed to hand out jobs** to the ambulance crews.

* **Centralized (A), control room down.** 112 calls still come in (another control room answers them),
  but nobody can hand them out. Crews who are free sit at their posts while calls wait in a pile. When
  the control room comes back, it must first work through that pile, so even calls made *after* the
  outage wait longer. The longer the outage, the bigger the pile: a 1-hour outage more than doubles the
  slowest response times (p95 21 → 49 min), and 2 hours almost quintuples them (→ 96 min).
* **Decentralized (B), always.** There is no one handing out jobs. Each call is announced to all crews,
  free crews say how far away they are, and after a short wait (the 2-min bidding window) the closest
  one takes it. Nothing can break centrally, so an outage changes nothing. But every call, every day,
  pays the short wait and needs three messages instead of one, which is why B is slower on normal days
  and suffers more when radio messages get lost.
* **Hybrid (H).** Normally it is A: one person hands out jobs, fast and with one message per call. The
  moment the control room is unreachable, crews switch to announcing and claiming calls among
  themselves (B). **No pile builds up**, so when the control room is back there is nothing to catch up
  on and it simply takes over again. It is like a shop where the cashier's till breaks: instead of a
  queue forming at the till, customers use the self-checkout until the till works again, then go back
  to the cashier.

During the outage H does as well as B (the two are statistically level). The difference is the rest of
the day: H is back on the faster control room, while B keeps paying its bidding wait on every call.

**What H does *not* fix:** it only helps when the control room cannot hand out jobs **but calls still
arrive and crews can still talk to each other**. If people cannot reach 112, or the radio/data link is
down too, H is no better than A (see the next section).

---

## What this means in practice, and for whom

### What is in place today (from public sources)

* **One control room for five regions.** Twente's ambulance calls are handled by Meldkamer
  Oost-Nederland (MKON) in Apeldoorn, which serves five regions and 3.2 million residents. Another
  control room can take a 112 call, but handing out the ambulance stays with the region's own control
  room [NAZ-MkON]. That is exactly the single point of failure E4 models.
* **Real failures have been of other kinds.** On 24 June 2019, 112 was unreachable nationwide for about
  3½ hours (from about 16:00 to 19:27) because of a KPN fault, i.e. calls could not get **in** at all.
  Twente's response: it went to GRIP 2 at 16:49, published regional emergency numbers (including one for
  the ambulance) at 17:15, sent an NL-Alert at 18:14, staffed all 29 fire stations as places to report
  incidents, posted ambulances at police stations, and kept hospitals and moving ambulances in touch by
  radio [VRT-2019]. Crews were spread out and reachable directly, but this was improvised during the
  event, not a pre-planned dispatch fallback.
* **Strain on the control room, not a full outage.** In 2024 the Minister answered parliamentary
  questions about long 112 waiting times at MKON. The health inspectorate (IGJ) was keeping
  "geïntensiveerd toezicht" (intensified supervision) because of staffing. 112 systems can already
  re-route calls to other regions when busy. Pilots were announced to run the ambulance control-room
  function partly outside the control room. Ambulance crews in the region use a Push-to-Talk app next to
  the C2000 radio network, with C2000 handhelds and normal telephones as backup [TK-2024-2037].

### Which failures the hybrid would help with

| Failure | Example | Modelled? | Does H help? |
|---|---|---|---|
| Control room cannot hand out jobs; calls get in; crews reachable | IT or system failure at the dispatch desk | **Yes (E4)** | **Yes**: the outage cost is removed if the switch takes ≤ 10 min, most of it up to ~30 min |
| Calls cannot get in at all | 112 down, June 2019 | No | **No**: no dispatch method helps without the call; alternative numbers and visible posts do |
| Radio/data link down | C2000 or PTT failure | Partly (E3: message loss) | **No**: bidding needs more messages than central dispatch; with B at 50% message loss p95 roughly doubles |
| Control room overloaded or short-staffed | MKON waiting times, 2024 | Partly (E6) | **Not as designed**: H only switches on a full outage, not on a long queue |

### What it means for each group

* **Ambulance Oost (RAV Twente) and its crews.** Nothing should change on a normal day: the model finds
  central dispatch better every day, under heavy demand, and with poor communication. The useful idea is
  a **pre-agreed outage procedure**: if the control room cannot reach us, free crews claim the most
  urgent nearby calls among themselves by a fixed rule (most urgent first, closest crew wins), then hand
  back. This needs a rule crews have practised, a way to see open calls (e.g. via the PTT app or C2000),
  and clear ownership of each call. The model says nothing about crew workload or whether this is
  workable under stress; that needs exercises.
* **Meldkamer Oost-Nederland and the Landelijke Meldkamer Samenwerking.** The value of the fallback
  depends almost entirely on **how fast an outage is noticed and the switch is made**. For a 1-hour
  outage, the model keeps all of the gain with a switch within 10 min, ~90% at 20 min, ~70% at 30 min
  and ~25% at 50 min. A switch that only comes once the control room is back is slightly worse than no fallback.
  In 2019, Twente's formal crisis scale-up came about 50 min after the start and the regional numbers
  after about 75 min [VRT-2019]. That was a different kind of failure, so it is not a measured switchover
  time, but if a dispatch fallback were switched on at the speed of a crisis meeting, the model says
  most of its value would be gone. The practical lessons:
  - the trigger should be automatic or very simple ("no assignment received for X minutes"), aimed at
    10 min or less;
  - the hand-back should be just as quick, because bidding after recovery costs time;
  - the procedure is worth practising, because how fast it starts matters more than how it works.
* **Veiligheidsregio Twente / GHOR.** The fallback is a small addition to existing outage plans, which
  in 2019 focused on letting people report emergencies some other way. It covers the case those plans
  did not: calls arrive, but nobody can send a unit.
* **Hospitals (MST, ZGT).** In the model, the fallback changes *when* patients reach the ambulance, not how
  many are served: unserved calls are the same for all modes (all 0.5–0.8%). The effect on emergency-
  department arrival peaks was not measured. The fallback does not change hospital capacity, which E2
  shows is the real limit at high demand.
* **Ministry of VWS and IGJ.** The study puts a number on the risk of having a single control room. At
  1.25× normal demand, a 1-hour dispatch outage takes the slowest 5% of urgent responses from 21 to 49 min,
  and a 2-hour one to 96 min. A cheap, rule-based fallback removes most of that **in the model**.
  Whether it does so in practice depends on the switchover time (in the model, a fallback switched on
  after 30 min keeps ~70% of the gain, after 50 min ~25%) and on the radio link (not tested here). It is an argument for asking control rooms to plan and exercise a dispatch-outage procedure, not
  for decentralizing dispatch. It also does not address the 2024 staffing problem: the model's operators
  are idealised (E6), and real queueing at MKON was worse than the model allows.
* **Patients and the public.** Nothing changes for them on a normal day. During a rare control-room
  failure, the fallback is about the slowest urgent calls not getting much slower. For cardiac arrest,
  every minute counts (Larsen et al. 1993; argued from literature, not simulated).

### Bottom line

This study does **not** recommend changing day-to-day dispatch. It **prices the single-point-of-failure
risk** of the current centralized model and shows that a cheap fallback can remove most of it, **under
three conditions**: the outage is noticed and the switch made quickly (in the model, within ~10 min for
the full gain; the value fades from 20–30 min and is gone if the switch comes after the control room
is back), crews can still exchange messages, and 112 calls still get in. The first is measured here; the
other two are assumed.

## What the model measured vs what is argued from literature

| **Measured by the model** | **Argued from literature only, NOT model results** |
|---|---|
| Response times (mean, p95, % within 15 min), by urgency | Whether paramedic crews could run an auction in practice |
| Unserved calls, utilization, hospital diversions, offload delay | Workload and stress for dispatchers and crews |
| Urban–rural gap, message counts, bids per call, operator queueing | Legal responsibility when no dispatcher assigns a unit |
| Effect of demand, message loss/delay, outage, bidding window, operator staffing | Survival impact of minutes saved; feasibility of a robust data link |

---

## Main limitations

* **Abstract map.** Straight-line distance × 1.3 for roads at an average speed; no real road network,
  traffic or time of day.
* **Calibrated to one region** (Twente) against national and regional targets; several inputs are
  `[ASSUMPTION]` values chosen by calibration (fleet on duty, speed, ED places and stay).
* **Operators are idealised.**
  - **Staffing:** 1 on shift is Twente's pro-rata share of a pooled 5-region team. It is not a
    published per-region figure.
  - **Workload:** each operator handles both call-taking and dispatch, and is busy only for the 2-min
    processing.
  - **The decentralized mode** is given unlimited call-takers.
* **The bidding window is a design parameter**, not a physical constant. The 1-min floor comes from the
  model's 1-minute time step.
* **The auction's urgency rule is one design choice of ours.** Other rules could do better or worse.
* Lost messages are noticed and retried at once, which flatters both modes, but the auction more
  in absolute terms, because it sends more messages.
* Constant call rate (no day/night pattern), so hourly counts vary only by chance
  (`results/incidents_report.md`); one ambulance per call; the offload anchor (WAITED) is one
  Rotterdam hospital group.
* **The hybrid's switch is idealised.** Detection and activation take a fixed `SWITCHOVER_DELAY_MIN`
  (0 by default, the best case; 0–60 min tested at one outage length, 60 min, and one demand level). The auction's radio/data link is assumed to keep
  working while the control room is down, and call-taking (a neighbouring meldkamer) to keep announcing
  calls. A failure that takes out the link as well would leave H no better than A. Other outage lengths and demand
  levels were not swept for the delay; the delay is the same for switching on and handing back.
