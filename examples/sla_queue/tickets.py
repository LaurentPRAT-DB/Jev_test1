"""A stand-in for the message queue. Yields a batch of support tickets.

Each ticket carries business metadata (`sla`) alongside the raw `body`. Note
T1 and T2 have IDENTICAL bodies but different SLA tiers — the whole point of
the example: same content, different criticality.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ticket:
    id: str
    sla: str          # enterprise | business | free
    body: str


_SAME = "Your API intermittently returns HTTP 500 on POST /v2/events. About 1 in 5 requests fails and our retry queue is backing up."

BATCH: list[Ticket] = [
    Ticket("T1", "enterprise", _SAME),
    Ticket("T2", "free", _SAME),  # identical content, different SLA
    Ticket("T3", "business",
           "The dashboard header color looks slightly off since the latest update. Not a big deal, just mentioning it."),
    Ticket("T4", "free",
           "Complete outage — nothing loads, every page 503s, this is costing us customers right now!!"),
    Ticket("T5", "enterprise",
           "Hi team, could you share the roadmap for the new reporting module? Planning our next quarter."),
    Ticket("T6", "business",
           "Login works but is slow, ~8s to authenticate. Users are complaining but can still get in."),
]


def pull_batch() -> list[Ticket]:
    """Simulate consuming a batch of messages from the queue."""
    return list(BATCH)
