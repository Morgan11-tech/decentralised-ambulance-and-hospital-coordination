"""
channel.py — Message passing between agents.

All coordination messages go through one Channel, which is also where we inject
communication failure for the resilience experiments:
  loss_prob   probability a message is dropped
  delay_ticks ticks a message is held before delivery
Both default to 0 (perfect comms), so the channel is transparent until we turn
the knobs up. Agents never read each other's state directly; they send messages.
"""

from dataclasses import dataclass, field


@dataclass
class Message:
    kind: str                     # "AWARD" now; "ANNOUNCE"/"BID" added for decentralized
    sender: object = None
    recipient: object = None      # an agent, or None = broadcast to all ambulances
    incident: object = None
    session_id: str = None
    payload: dict = field(default_factory=dict)


class Channel:
    def __init__(self, model, loss_prob=0.0, delay_ticks=0):
        self.model = model
        self.loss_prob = loss_prob
        self.delay_ticks = delay_ticks
        self._queue = []          # (deliver_tick, message)
        self.sent_counts = {}     # messages transmitted, by kind

    def send(self, msg):
        """Queue a message. Returns False if it was dropped (lost)."""
        self.sent_counts[msg.kind] = self.sent_counts.get(msg.kind, 0) + 1
        if self.loss_prob > 0 and self.model.random.random() < self.loss_prob:
            return False
        self._queue.append((self.model.clock + self.delay_ticks, msg))
        return True

    def deliver_due(self):
        """Move all messages whose time has come into recipient inboxes. Once per tick."""
        still = []
        for deliver_tick, msg in self._queue:
            if deliver_tick <= self.model.clock:
                recipients = ([msg.recipient] if msg.recipient is not None
                              else list(self.model.ambulances))
                for r in recipients:
                    r.inbox.append(msg)
            else:
                still.append((deliver_tick, msg))
        self._queue = still