"""
model.py — The simulation model (step 4).

Centralized baseline with real hospitals. Order each tick:
  1. release due incidents
  2. hospitals step (free finished stays, update diversion)
  3. dispatcher assigns nearest idle unit (most urgent first)
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
_LOG_CAP = 300


class EmergencyModel(mesa.Model):
    def __init__(self, seed=config.SEED, incident_file=None, mode=None,
                 n_ambulances=None, loss_prob=None, delay_ticks=None,
                 outage_start=0, outage_len=0, incidents=None):
        super().__init__(rng=seed)
        self.mode = mode or config.MODE
        n_amb = n_ambulances or config.N_AMBULANCES
        lp = config.LOSS_PROB if loss_prob is None else loss_prob
        dt = config.DELAY_TICKS if delay_ticks is None else delay_ticks
        # dispatcher outage window (centralized only): control room unreachable
        self.dispatcher_outage = (outage_start, outage_start + outage_len) if outage_len > 0 else None

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
            self.incidents = incidents_from_records(incidents, seed=seed)
        else:
            path = incident_file or config.INCIDENT_FILE
            if not os.path.exists(path):
                fallback = "incident_sample.json"
                if os.path.exists(fallback):
                    print(f"[warn] {path} not found; using {fallback}")
                    path = fallback
                else:
                    print(f"[warn] no incident file found ({path}); running with no incidents")
                    path = None
            self.incidents = load_incidents(path, seed=seed) if path else []

        self.clock = 0
        self._next_idx = 0
        self.active_incidents = []
        self.completed = []
        self.busy_ticks = 0        # cumulative ambulance-ticks spent busy
        self.n_diversions = 0      # count of hospital diversion onsets
        self.metrics = {}
        self.datacollector = DataCollector(model_reporters={
            "completed": lambda m: len(m.completed),
            "waiting": lambda m: len(m.active_incidents) + len(m.auctions),
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
        )

        self.running = True

    # --- logging -----------------------------------------------------------
    def log(self, msg):
        self.event_log.append(f"{self.clock:>4} | {msg}")
        if len(self.event_log) > _LOG_CAP:
            self.event_log = self.event_log[-_LOG_CAP:]

    # --- incident release --------------------------------------------------
    def _release_due_incidents(self):
        while (self._next_idx < len(self.incidents)
               and self.incidents[self._next_idx].created_tick <= self.clock):
            inc = self.incidents[self._next_idx]
            self.active_incidents.append(inc)
            self.log(f"[new] {inc.code} {inc.incident_id}")
            self._next_idx += 1

    # --- centralized allocation (condition A) ------------------------------
    def _dispatch_centralized(self):
        if self.dispatcher_outage is not None:
            start, end = self.dispatcher_outage
            if start <= self.clock < end:
                return     # control room down: no assignments get out
        idle = [a for a in self.ambulances if a.status == "IDLE" and not a._reserved]
        if not idle or not self.active_incidents:
            return
        idle = [a for a in idle if not a._reserved]
        waiting = sorted(self.active_incidents,
                         key=lambda inc: (_PRIORITY.get(inc.code, 9), inc.created_tick))
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

    # --- decentralized allocation (condition B: Contract Net) --------------
    def _dispatch_decentralized(self):
        t = self.clock
        # 1) collect bids delivered since last tick
        for msg in self.inbox:
            if msg.kind == "BID":
                au = self.auctions.get(msg.incident.incident_id)
                if au is not None:
                    au["bids"].append(msg.payload)
        self.inbox.clear()

        # 2) announce every active incident not already under auction
        for inc in list(self.active_incidents):
            if inc.incident_id not in self.auctions:
                if self.channel.send(Message("ANNOUNCE", recipient=None, incident=inc)):
                    deadline = t + config.BID_WINDOW_TICKS + 2 * self.channel.delay_ticks
                    self.auctions[inc.incident_id] = {
                        "incident": inc, "deadline": deadline, "bids": []}
                    self.active_incidents.remove(inc)
                # if the announce is dropped, leave it active and retry next tick

        # 3) resolve auctions whose bidding window has closed
        for iid, au in list(self.auctions.items()):
            if t < au["deadline"]:
                continue
            # winner = lowest ETA among bidders still free (status read used only to
            # validate the award, not to make the allocation, which used the bids)
            cands = [b for b in au["bids"]
                     if b["amb"].status == "IDLE" and not b["amb"]._reserved]
            if cands:
                win = min(cands, key=lambda b: (b["eta"], b["amb"].unique_id))
                amb = win["amb"]
                if self.channel.send(Message("AWARD", recipient=amb, incident=au["incident"],
                                             session_id=au["incident"].session_id)):
                    amb._reserved = True
                    self.log(f"[auction] {au['incident'].incident_id} -> amb#{amb.unique_id} "
                             f"(eta {win['eta']:.0f}m, {len(au['bids'])} bids)")
                else:
                    self.active_incidents.append(au["incident"])   # award lost: retry
            else:
                self.active_incidents.append(au["incident"])       # no usable bid: retry
            del self.auctions[iid]

    # --- main loop ---------------------------------------------------------
    def step(self):
        self._release_due_incidents()
        for h in self.hospital_agents:
            h.step()
        self.channel.deliver_due()      # deliver BIDs sent last tick BEFORE we collect them
        if self.mode == "centralized":
            self._dispatch_centralized()
        else:
            self._dispatch_decentralized()
        self.channel.deliver_due()      # AWARD messages -> inboxes (same tick at delay 0)
        for a in self.ambulances:
            a.step()
        self.busy_ticks += sum(1 for a in self.ambulances if a.status != "IDLE")
        self.clock += 1
        self.metrics = metrics.summary(self)
        self.datacollector.collect(self)