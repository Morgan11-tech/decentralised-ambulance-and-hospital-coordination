# Presentation pack — six figures and what each one says

The figures in this folder are copied from `../figures/` by `experiments/analyze.py`, so they are
refreshed whenever the analysis runs. The numbers in these notes come from the run of 30 simulated
days per setting (seeds 101–130) that produced `../tables.md`. Check them against that file after any
re-run.

**Set-up in one line:**
- **Centralized (A):** 1 operator on shift, most urgent call first.
- **Decentralized (B):** Contract Net auction, also most urgent first.

Both pay 2 min of call processing. Only A needs a shared operator for it.

**Colours throughout:** blue = centralized (A), purple = decentralized auction (B), green = hybrid (H,
E4 only: A, with the auction as fallback while the control room is down). Line = mean over
the 30 days; shaded band = middle 50% of days; dashed line = the 15-minute norm.

---

### 1. `E2_load_p95_unserved.png` — what happens as demand rises

Centralized dispatch keeps urgent calls fastest at every demand level. At normal demand the gap is
the bidding window (p95 17.5 vs 19.6 min). Under load it grows: at 2× demand, the slowest 5% of urgent
patients wait 167 min with a dispatcher against 229 min with the auction. From about 1.5× demand the
emergency departments are full, and both modes leave the same share of calls unserved: the hospitals,
not dispatch, set the limit.

### 2. `E3_message_loss.png` — the auction depends on good communication

Losing messages barely affects a dispatcher, which sends one message per call (p95 17.5 → 19.3 min at
50% loss). The auction needs three messages per call (announce → bid → award), and its p95 roughly
doubles (19.6 → 39.7 min). **Take-away:** a decentralized backup is only as good as the radio/data
link behind it.

### 3. `E4_outage_p95.png` — the one situation where the auction wins

When the control room goes down (at 1.25× demand), the dispatcher's calls pile up, but the auction has
no central point to lose. For calls made during the outage and the hour after, the auction is clearly
better from 30 minutes of outage (p95 25 vs 30 min), and after a 120-min outage it is 30 vs 96 min.
The green line tests that fallback directly: with no outage it is identical to A, and during an outage
it is level with B (60-min outage: p95 27 min vs 49 for A and 27 for B). It gets B's resilience without
B's everyday cost.
**Take-away:** a decentralized auction is a plausible *fallback*, not a replacement. The study does not
argue for changing day-to-day dispatch; it prices the single-point-of-failure risk and shows that a
cheap fallback removes it.

### 3b. `E4_switchover_delay.png` — how fast must the fallback switch on?

The hybrid needs someone (or something) to notice the outage and switch to bidding. For a 1-hour
outage: switching within 10 min keeps all the gain (p95 26–27 min vs 49 without a fallback); at
20 min it is 29, at 30 min 33, at 50 min 44, and if the switch only comes once the control room is
already back (60 min) it is 51, slightly worse than no fallback. **Take-away:** the speed of the trigger matters more
than the fallback itself; it should be automatic, not wait for a crisis meeting (Twente took ~50 min to
reach GRIP 2 in the 2019 112 outage). The model assumes the radio/data link survives the outage.

### 4. `E5_bid_window.png` — the everyday cost is a tunable design choice

At normal demand, the auction's everyday penalty equals its bidding window, minute for minute: a 1-min
window costs 1.4 min at p95, a 3-min window 3.2 min. A zero window never works, because the auction
closes before any bid can arrive. **Take-away:** the window is the price of not having a central view of
who is free.

### 5. `E6_operators.png` — does centralized only win because the control room is well staffed?

No. With one operator, centralized p95 is within about 1 min of unlimited operators (not
statistically clear). With two or more at normal demand (three at 1.25×), it is identical. Even at 5× demand, urgent calls wait only
about 1 min for an operator, while the wait for an ambulance runs to hundreds of minutes (right panel).
**Take-away:** at Twente's call volumes the bottleneck is ambulances and beds, not call-takers. Caveat:
our operators are idealised (no after-call work), so this is a best case for the control room.
