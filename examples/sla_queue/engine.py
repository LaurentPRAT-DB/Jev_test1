"""Get the raw, SLA-blind probability `p` per ticket body — three backends.

- stub:      deterministic, offline, no API (default; identical body -> identical p).
- jev:       one batched TypeSafe System One call via typesafe_sdk (raw noul p,
             NOT bool-coerced, so the per-SLA cut can be applied downstream).
- ai_decide: one batched Databricks SQL call; reads the raw VARIANT probability.

All three return a list[float] aligned to the input bodies. One call per batch
either way — content is queried once; SLA thresholds are applied later in code.
"""

from __future__ import annotations

import json
import subprocess

PROFILE = "FEVM_SERVERLESS_STABLE"

# Offline stand-in for the model: a transparent keyword heuristic. NOT a model —
# just enough signal that identical bodies get identical, semantically plausible
# p so the SLA routing demo is meaningful without spending any credit. Swap for
# backend="jev" / "ai_decide" for real probabilities.
_SEVERE = ("outage", "503", "500", "down", "costing", "data loss", "blocked",
           "failing", "fails", "crash", "unusable", "nothing loads")
_MILD = ("slow", "intermittent", "degraded", "complain", "backing up")
_TRIVIAL = ("color", "roadmap", "planning", "slightly", "not a big deal",
            "nit", "question", "mentioning")


def probs_stub(bodies: list[str]) -> list[float]:
    out = []
    for b in bodies:
        t = b.lower()
        p = 0.10
        p += 0.20 * sum(k in t for k in _SEVERE)
        p += 0.12 * sum(k in t for k in _MILD)
        p -= 0.10 * sum(k in t for k in _TRIVIAL)
        out.append(round(min(0.98, max(0.02, p)), 3))
    return out


def _noul_question(cfg: dict):
    from typesafe_sdk import Noul
    q = cfg["question"]
    return Noul(instructions=q["instructions"], criteria=q.get("criteria"))


def probs_jev(bodies: list[str], cfg: dict) -> list[float]:
    """One batched System One call -> raw noul probability per body."""
    from typesafe_sdk import TypeSafeClient

    base = _noul_question(cfg)
    name = cfg["question"]["name"]
    batched = {
        f"{i}:{name}": type(base)(
            instructions=f"For the item at index {i} in the state array: {base.instructions}",
            criteria=base.criteria,
        )
        for i in range(len(bodies))
    }
    resp = TypeSafeClient().system_one(state=list(bodies), questions=batched)
    return [resp.nouls[f"{i}:{name}"].noul for i in range(len(bodies))]


def probs_ai_decide(bodies: list[str], cfg: dict) -> list[float]:
    """One batched ai_decide SQL call -> raw VARIANT probability per body."""
    q = cfg["question"]
    questions_json = json.dumps(
        {q["name"]: {"type": "noul", "instructions": q["instructions"], "criteria": q.get("criteria")}}
    )

    def lit(s: str) -> str:
        return "'" + s.replace("'", "''") + "'"

    values = ", ".join(f"({lit(str(i))}, {lit(b)})" for i, b in enumerate(bodies))
    sql = (f"SELECT id, ai_decide(state, {lit(questions_json)}) AS d "
           f"FROM VALUES {values} AS t(id, state)")
    proc = subprocess.run(
        ["databricks", "experimental", "aitools", "tools", "query", sql, "--profile", PROFILE],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip())
    by_id = {}
    for row in json.loads(proc.stdout):
        d = json.loads(row["d"])
        by_id[int(row["id"])] = d["response"]["answers"][q["name"]]["probability"]
    return [by_id[i] for i in range(len(bodies))]


BACKENDS = {"stub": probs_stub, "jev": probs_jev, "ai_decide": probs_ai_decide}


def get_probs(bodies: list[str], cfg: dict, backend: str = "stub") -> list[float]:
    fn = BACKENDS[backend]
    return fn(bodies) if backend == "stub" else fn(bodies, cfg)
