"""
agents.py — Agent classes (step 4).

Ambulance lifecycle:
  IDLE -> EN_ROUTE -> ON_SCENE -> [TO_HOSPITAL -> (WAITING ->) HANDOVER ->] RETURNING -> IDLE

Hospital:
  a set of `capacity` servers. A patient holds a server for its length of stay.
  The ED goes ON DIVERSION at DIVERSION_THRESHOLD occupancy for DIVERSION_DURATION_MIN,
  declining ambulances. If BOTH EDs are full, the ambulance waits (offload delay).
"""

import math

import mesa

import config
from channel import Message


class Hospital(mesa.Agent):
    def __init__(self, model, name, pos, capacity):
        super().__init__(model)
        self.name = name
        self.home_pos = pos
        self.capacity = capacity
        self.occupied = []          # free-ticks of occupied servers
        self.on_diversion = False
        self.diversion_until = None

    @property
    def load(self):
        return len(self.occupied)

    def can_accept(self):
        return (not self.on_diversion) and self.load < self.capacity

    def admit(self, incident, now):
        self.occupied.append(now + incident.los_min)   # holds a server for its LOS

    def step(self):
        t = self.model.clock
        self.occupied = [ft for ft in self.occupied if ft > t]   # free finished stays
        frac = self.load / self.capacity
        if not self.on_diversion and frac >= config.DIVERSION_THRESHOLD:
            self.on_diversion = True
            self.diversion_until = t + config.DIVERSION_DURATION_MIN
            self.model.n_diversions += 1
            self.model.log(f"[divert] {self.name} ON diversion ({self.load}/{self.capacity})")
        elif self.on_diversion and (t >= self.diversion_until
                                    or frac <= config.DIVERSION_CLEAR_THRESHOLD):
            self.on_diversion = False
            reason = "window" if t >= self.diversion_until else "cleared"
            self.model.log(f"[divert] {self.name} reopened ({reason}, {self.load}/{self.capacity})")


class Ambulance(mesa.Agent):
    def __init__(self, model, home_pos, speed_kmh=config.EFFECTIVE_SPEED_KMH):
        super().__init__(model)
        self.home_pos = home_pos
        self.target = None
        self.speed_kmh = speed_kmh
        self.status = "IDLE"
        self.current_incident = None
        self.dest_hospital = None
        self.busy_until = None
        self.offload_start = None
        self.inbox = []          # messages delivered by the Channel
        self._reserved = False   # dispatcher has sent an AWARD not yet processed

    # --- movement ----------------------------------------------------------
    def _step_km(self):
        return (self.speed_kmh * (config.TICK_MINUTES / 60.0)) / config.DETOUR_FACTOR

    def _advance_to_target(self):
        x, y = self.pos
        tx, ty = self.target
        dx, dy = tx - x, ty - y
        dist = math.hypot(dx, dy)
        step_km = self._step_km()
        if dist <= step_km or dist == 0:
            self.model.space.move_agent(self, (tx, ty))
            return True
        self.model.space.move_agent(self, (x + dx / dist * step_km, y + dy / dist * step_km))
        return False

    # --- hospital choice ---------------------------------------------------
    def _nearest(self, hospitals):
        return min(hospitals, key=lambda h: math.hypot(h.home_pos[0] - self.pos[0],
                                                       h.home_pos[1] - self.pos[1]))

    def _choose_hospital(self):
        hosps = self.model.hospital_agents
        accepting = [h for h in hosps if h.can_accept()]
        return self._nearest(accepting if accepting else hosps)

    def _other_accepting(self):
        alts = [h for h in self.model.hospital_agents
                if h is not self.dest_hospital and h.can_accept()]
        return self._nearest(alts) if alts else None

    # --- dispatcher hook ---------------------------------------------------
    def assign(self, incident, now):
        self._reserved = False
        self.current_incident = incident
        incident.assigned_tick = now
        self.target = incident.pos
        self.status = "EN_ROUTE"
        self.model.log(f"[assign] amb#{self.unique_id} -> {incident.code} {incident.incident_id}")

    # --- per-tick behaviour ------------------------------------------------
    def step(self):
        t = self.model.clock
        # process coordination messages first
        for msg in self.inbox:
            if msg.kind == "AWARD" and self.status == "IDLE":
                self.assign(msg.incident, t)
            elif msg.kind == "ANNOUNCE" and self.status == "IDLE" and not self._reserved:
                # Contract Net: bid my ETA to this incident (decentralized condition)
                inc = msg.incident
                d = math.hypot(inc.pos[0] - self.pos[0], inc.pos[1] - self.pos[1])
                eta = config.travel_time_min(d)
                self.model.channel.send(Message("BID", sender=self, recipient=self.model,
                                                incident=inc, payload={"eta": eta, "amb": self}))
        self.inbox.clear()

        inc = self.current_incident

        if self.status == "EN_ROUTE":
            if self._advance_to_target():
                inc.on_scene_tick = t
                self.status = "ON_SCENE"
                self.busy_until = t + inc.on_scene_min
                self.model.log(f"[on-scene] {inc.incident_id} (resp {inc.response_min}m)")

        elif self.status == "ON_SCENE":
            if t >= self.busy_until:
                if inc.transport_needed:
                    self.dest_hospital = self._choose_hospital()
                    self.target = self.dest_hospital.home_pos
                    self.status = "TO_HOSPITAL"
                    self.model.log(f"[transport] {inc.incident_id} -> {self.dest_hospital.name}")
                else:
                    self.model.log(f"[on-site] {inc.incident_id} resolved on scene (no transport)")
                    self._finish(inc, t)

        elif self.status == "TO_HOSPITAL":
            if self._advance_to_target():
                if self.dest_hospital.can_accept():
                    self._admit(inc, t)
                else:
                    alt = self._other_accepting()
                    if alt:
                        self.dest_hospital = alt
                        self.target = alt.home_pos
                        self.model.log(f"[divert->] {inc.incident_id} to {alt.name}")
                    else:
                        self.status = "WAITING"
                        self.offload_start = t
                        self.model.log(f"[offload] {inc.incident_id} waiting (both EDs full)")

        elif self.status == "WAITING":
            if self.dest_hospital.can_accept():
                inc.offload_min = t - self.offload_start
                self._admit(inc, t)
            else:
                alt = self._other_accepting()
                if alt:
                    inc.offload_min = t - self.offload_start
                    self.dest_hospital = alt
                    self.target = alt.home_pos
                    self.status = "TO_HOSPITAL"
                    self.model.log(f"[divert->] {inc.incident_id} leaving wait for {alt.name}")

        elif self.status == "HANDOVER":
            if t >= self.busy_until:
                self._finish(inc, t)

        elif self.status == "RETURNING":
            if self._advance_to_target():
                self.status = "IDLE"
                self.target = None

    def _admit(self, inc, t):
        self.dest_hospital.admit(inc, t)
        self.status = "HANDOVER"
        self.busy_until = t + config.HANDOVER_MIN
        self.model.log(f"[admit] {inc.incident_id} @ {self.dest_hospital.name} "
                       f"({self.dest_hospital.load}/{self.dest_hospital.capacity})")

    def _finish(self, inc, t):
        inc.closed_tick = t
        self.model.complete(inc)
        self.model.log(f"[done] {inc.incident_id} (resp {inc.response_min}m)")
        self.current_incident = None
        self.dest_hospital = None
        self.target = self.home_pos
        self.status = "RETURNING"