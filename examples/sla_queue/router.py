"""Business routing: turn a content-only probability into an SLA-aware verdict.

The model's `p` is SLA-blind (content only). Criticality is a deterministic
business rule here — the SLA selects the cut points, so the same `p` routes
differently per tier. Pure functions, no API, no model: unit-testable offline.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("sla_config.json")


def load_config(path: Path | str = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


# verdict -> what to do with it
ACTIONS = {
    "CRITICAL": "page on-call",
    "REVIEW": "human queue",
    "ROUTINE": "auto-ack / backlog",
}


def route(sla: str, p: float, cfg: dict) -> tuple[str, str]:
    """(verdict, action) for a ticket's SLA tier and content probability `p`."""
    cuts = cfg["sla_cuts"].get(sla)
    if cuts is None:
        raise KeyError(f"no SLA cut configured for tier {sla!r}")
    if p >= cuts["critical"]:
        verdict = "CRITICAL"
    elif p >= cuts["review"]:
        verdict = "REVIEW"
    else:
        verdict = "ROUTINE"
    return verdict, ACTIONS[verdict]
