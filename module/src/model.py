"""
model.py — The simulation model (step 4).

Centralized dispatcher (A) vs decentralized Contract Net (B), with real hospitals, plus a fallback
hybrid (H): centralized while the control room is up, Contract Net while it is down (E4 only).
Order each tick:
  1. call processing (DISPATCH_HANDLING_MIN): in A a call needs a free operator
     (N_DISPATCH_OPERATORS) and may queue for one; in B every call is processed at once;
     H takes calls like A (call-taking survives a dispatch outage)
  2. hospitals step (free finished stays, update diversion)
  3. allocation, most urgent first: A assigns the nearest idle unit; B runs auctions;
     H does A, or B while self-dispatch is active (_self_dispatch_active)
  4. ambulances step (move / treat / transport / hand over)
"""

import math
import os

import mesa

import config
from agents import Ambulance, Hospital
from incidents import incidents_from_records, load_incidents
from channel import Channel, Message
from mesa.datacollection import DataCollector
import metrics

_PRIORITY = {"A0": 0, "A1": 1, "A2": 2, "B": 3}
MODES = ("centralized", "decentralized", "hybrid")
_LOG_CAP = 300


class EmergencyModel(mesa.Model):
    def __init__(self, seed=config.SEED, incident_file=None, mode=None,
                 n_ambulances=None, loss_prob=None, delay_ticks=None,
                 outage_start=0, outage_len=0, incidents=None, n_operators=None,
                 switchover_delay=None, incidents_t0=None):
        super().__init__(rng=seed)
        self.mode = mode or config.MODE
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        n_amb = n_ambulances or config.N_AMBULANCES
        lp = config.LOSS_PROB if loss_prob is None else loss_prob
        dt = config.DELAY_TICKS if delay_ticks is None else delay_ticks
        # call-takers/dispatchers on shift (centralized only); None in config = unlimited
        ops = config.N_DISPATCH_OPERATORS if n_operators is None else n_operators
        self.n_operators = math.inf if ops is None else ops
        # dispatcher outage window (centralized and hybrid): control room unreachable
        self.dispatcher_outage = (outage_start, outage_start + outage_len) if outage_len > 0 else None
        # hybrid only: minutes to detect the outage / the recovery and switch over
        self.switchover_delay = (config.SWITCHOVER_DELAY_MIN if switchover_delay is None
                                 else switchover_delay)

        self.space = mesa.space.ContinuousSpace(
            config.SPACE_WIDTH_KM, config.SPACE_HEIGHT_KM, torus=False
        )
        self.posts = config.POSTS_XY
        self.event_log = []
        self.channel = Channel(self, loss_prob=lp, delay_ticks=dt)
        self.inbox = []          # bids arrive here in the decentralized condition
        self.auctions = {}       # incident_id -> open Contract Net auction

        # Hospitals as agents.
        self.hospital_agents = []
        for name, h in config.HOSPITALS_XY.items():
            hosp = Hospital(self, name, h["pos"], h["capacity"])
            self.space.place_agent(hosp, h["pos"])
            self.hospital_agents.append(hosp)

        # Ambulances at posts (round-robin), idle.
        self.ambulances = []
        post_items = list(config.POSTS_XY.items())
        for i in range(n_amb):
            _, pos = post_items[i % len(post_items)]
            amb = Ambulance(self, home_pos=pos)
            self.space.place_agent(amb, pos)
            self.ambulances.append(amb)

        # Incidents: records passed in directly (e.g. one voice-agent incident)
        # take precedence over the incident file.
        if incidents is not None:
            self.incidents = incidents_from_records(incidents, seed=seed, t0=incidents_t0)
        else:
            path = incident_file or config.INCIDENT_FILE
            if not os.path.exists(path):
                fallback = "data/incident_sample.json"
                if os.path.exists(fallback):
                    print(f"[warn] {path} not found; using {fallback}")
                    path = fallback
                else:
                    print(f"[warn] no incident file found ({path}); running with no incidents")
                    path = None
            self.incidents = load_incidents(path, seed=seed) if path else []

        self.clock = 0
        self._next_idx = 0
        self.call_queue = []       # calls received, waiting for processing (A: for a free operator)
        self.operators = []        # (free_tick, incident) per busy operator (A only)
        self.max_call_queue = 0    # longest operator queue seen
        self.active_incidents = []
        self.completed = []
        self.busy_ticks = 0        # cumulative ambulance-ticks spent busy
        self.n_diversions = 0      # count of hospital diversion onsets
        self.metrics = {}
        self.datacollector = DataCollector(model_reporters={
            "completed": lambda m: len(m.completed),
            "waiting": lambda m: (len(m.call_queue) + len(m.operators)
                                  + len(m.active_incidents) + len(m.auctions)),
            "call_queue": lambda m: len(m.call_queue),
            "resp_mean": lambda m: m.metrics.get("resp_mean", float("nan")),
            "resp_p95": lambda m: m.metrics.get("resp_p95", float("nan")),
            "within15_pct": lambda m: m.metrics.get("within15_pct", float("nan")),
            "utilization_pct": lambda m: m.metrics.get("utilization_pct", float("nan")),
            "on_diversion": lambda m: sum(1 for h in m.hospital_agents if h.on_diversion),
        })

        # Remember how this model was built, so the "compare modes" panel can
        # rebuild BOTH conditions on the identical incidents and settings.
        self._build_kwargs = dict(
            seed=seed, incident_file=incident_file, n_ambulances=n_ambulances,
            loss_prob=loss_prob, delay_ticks=delay_ticks,
            outage_start=outage_start, outage_len=outage_len, incidents=incidents,
            n_operators=n_operators, switchover_delay=switchover_delay,
            incidents_t0=incidents_t0,
        )

        self.running = True

    # --- logging -----------------------------------------------------------
    def log(self, msg):
        self.event_log.append(f"{self.clock:>4} | {msg}")
        if len(self.event_log) > _LOG_CAP:
            self.event_log = self.event_log[-_LOG_CAP:]

    # --- call processing ---------------------------------------------------
    def _process_calls(self):
        """Move calls through processing (DISPATCH_HANDLING_MIN) into active_incidents.

        Centralized: a call is processed by one of n_operators; it occupies that operator for
        the handling time, and when all are busy it waits, most urgent then oldest first.
        Decentralized: no shared operator, so every call is processed in parallel.
        With unlimited operators both give the same timing.
        """
        t, lag = self.clock, config.DISPATCH_HANDLING_MIN
        while self._next_idx < len(self.incidents) and self.incidents[self._next_idx].created_tick <= t:
            self.call_queue.append(self.incidents[self._next_idx])
            self._next_idx += 1
        if self.mode == "decentralized":
            for inc in [i for i in self.call_queue if i.created_tick + lag <= t]:
                inc.answered_tick = inc.created_tick
                self._release(inc)
                self.call_queue.remove(inc)
            return
        self._finish_operators(t)
        free = self.n_operators - len(self.operators)
        if free > 0 and self.call_queue:
            self.call_queue.sort(key=self._prio)
            for inc in self.call_queue[:free] if free < math.inf else list(self.call_queue):
                inc.answered_tick = t
                self.operators.append((t + lag, inc))
                self.call_queue.remove(inc)
            self._finish_operators(t)                  # zero handling time: released at once
        self.max_call_queue = max(self.max_call_queue, len(self.call_queue))

    def _finish_operators(self, t):
        done = [(ft, inc) for ft, inc in self.operators if ft <= t]
        for item in done:
            self.operators.remove(item)
            self._release(item[1])

    def _release(self, inc):
        self.active_incidents.append(inc)
        self.log(f"[new] {inc.code} {inc.incident_id}")

    @staticmethod
    def _prio(inc):
        return (_PRIORITY.get(inc.code, 9), inc.created_tick)

    # --- dispatcher availability (outage, E4) -------------------------------
    def _dispatcher_up(self):
        if self.dispatcher_outage is None:
            return True
        start, end = self.dispatcher_outage
        return not (start <= self.clock < end)

    def _self_dispatch_active(self):
        """Hybrid: units self-dispatch by Contract Net in [start + d, end + d), d = switchover_delay.
        The fallback needs d minutes to notice the outage (nothing gets out in [start, start + d))
        and d minutes to notice the recovery (units keep bidding in [end, end + d)). [ASSUMPTION]"""
        if self.dispatcher_outage is None:
            return False
        start, end = self.dispatcher_outage
        d = self.switchover_delay
        return start + d <= self.clock < end + d

    # --- centralized allocation (condition A) ------------------------------
    def _dispatch_centralized(self):
        if not self._dispatcher_up():
            return     # control room down: no assignments get out. Call-taking goes on
                       # (another meldkamer can take 112 calls; dispatch stays regional [NAZ-MkON])
        idle = [a for a in self.ambulances if a.status == "IDLE" and not a._reserved]
        if not idle or not self.active_incidents:
            return
        waiting = sorted(self.active_incidents, key=self._prio)
        for inc in waiting:
            if not idle:
                break
            best = min(idle, key=lambda a: math.hypot(a.pos[0] - inc.pos[0],
                                                      a.pos[1] - inc.pos[1]))
            # the assignment travels as a message, not a direct call
            if self.channel.send(Message("AWARD", recipient=best, incident=inc,
                                         session_id=inc.session_id)):
                best._reserved = True
                idle.remove(best)
                self.active_incidents.remove(inc)
            # if dropped (loss>0): incident stays active, unit stays idle -> retried

    def complete(self, incident):
        self.completed.append(incident)

    # --- auction timing ----------------------------------------------------
    def _open_auction(self, inc, t, window):
        if config.BID_WINDOW_KNOWS_DELAY:
            window += 2 * self.channel.delay_ticks          # wait for the known round trip
        return {"incident": inc, "opened": t, "deadline": t + window, "bids": [], "last_bid": None}

    def _auction_due(self, au, t):
        """Fixed window: close at the deadline. Early close: close once bids have come in and
        a tick has passed with no new bid, or at the cap."""
        if config.AUCTION_EARLY_CLOSE:
            if t >= au["opened"] + config.AUCTION_MAX_WINDOW_TICKS:
                return True
            return au["last_bid"] is not None and au["last_bid"] < t
        return t >= au["deadline"]

    # --- decentralized allocation (condition B: Contract Net, urgency-ordered) ----
    def _dispatch_decentralized(self, announce=True):
        """Contract Net (Smith 1980): announce each call, free units bid their ETA, and when
        the bidding window closes the lowest ETA wins. Urgency order, as in the centralized
        dispatcher (most urgent first):

        1. Calls are announced and auctions closed most urgent first (A0, A1, A2, then
           oldest), and a unit that has also bid on a still-open MORE urgent auction is held
           back for it rather than awarded a less urgent call. Uses only the bids, no reads
           of unit state.
        2. A0 (immediate_dispatch) auctions close after IMMEDIATE_BID_WINDOW_TICKS.

        announce=False (hybrid, back on the dispatcher): only collect bids and close the auctions
        still open; no new calls are announced, so open auctions resolve as they would have.
        """
        t = self.clock
        prio = self._prio
        for msg in self.inbox:
            if msg.kind == "BID":
                au = self.auctions.get(msg.incident.incident_id)
                # a bid counts only for the announcement it answers (Contract Net task id):
                # late replies to an auction that already closed are discarded
                if au is not None and msg.payload.get("auction") == au["opened"]:
                    au["bids"].append(msg.payload)
                    au["last_bid"] = t
        self.inbox.clear()

        for inc in sorted(self.active_incidents, key=prio) if announce else []:
            if inc.incident_id not in self.auctions:
                if self.channel.send(Message("ANNOUNCE", recipient=None, incident=inc,
                                             payload={"auction": t})):
                    window = (min(config.IMMEDIATE_BID_WINDOW_TICKS, config.BID_WINDOW_TICKS)
                              if inc.immediate_dispatch else config.BID_WINDOW_TICKS)
                    self.auctions[inc.incident_id] = self._open_auction(inc, t, window)
                    self.active_incidents.remove(inc)

        open_aus = sorted(self.auctions.items(), key=lambda kv: prio(kv[1]["incident"]))
        for iid, au in open_aus:
            if not self._auction_due(au, t):
                continue
            p = _PRIORITY.get(au["incident"].code, 9)
            held = {id(b["amb"]) for jid, other in self.auctions.items()
                    if jid != iid and not self._auction_due(other, t)
                    and _PRIORITY.get(other["incident"].code, 9) < p
                    for b in other["bids"]}
            cands = [b for b in au["bids"]
                     if b["amb"].status == "IDLE" and not b["amb"]._reserved
                     and id(b["amb"]) not in held]
            if cands:
                win = min(cands, key=lambda b: (b["eta"], b["amb"].unique_id))
                amb = win["amb"]
                if self.channel.send(Message("AWARD", recipient=amb, incident=au["incident"],
                                             session_id=au["incident"].session_id)):
                    amb._reserved = True
                    self.log(f"[auction] {au['incident'].incident_id} -> amb#{amb.unique_id} "
                             f"(eta {win['eta']:.0f}m, {len(au['bids'])} bids)")
                else:
                    self.active_incidents.append(au["incident"])
            else:
                self.active_incidents.append(au["incident"])
            del self.auctions[iid]

    # --- main loop ---------------------------------------------------------
    def step(self):
        self._process_calls()
        for h in self.hospital_agents:
            h.step()
        self.channel.deliver_due()      # deliver BIDs sent last tick BEFORE we collect them
        if self.mode == "centralized":
            self._dispatch_centralized()
        elif self.mode == "decentralized":
            self._dispatch_decentralized()
        elif self._self_dispatch_active():          # hybrid, control room down: units bid
            self._dispatch_decentralized()
        else:                                       # hybrid, control room up (or not yet noticed down)
            if self.auctions or self.inbox:         # auctions opened before the switch-back finish first;
                self._dispatch_decentralized(announce=False)   # an unawarded call returns to the queue
            self._dispatch_centralized()            # dispatcher takes only calls still in active_incidents
        self.channel.deliver_due()      # AWARD messages -> inboxes (same tick at delay 0)
        for a in self.ambulances:
            a.step()
        self.busy_ticks += sum(1 for a in self.ambulances if a.status != "IDLE")
        self.clock += 1
        self.metrics = metrics.summary(self)
        self.datacollector.collect(self)