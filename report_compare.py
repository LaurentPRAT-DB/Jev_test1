"""Compare Databricks ai_decide vs TypeSafe jev on a complex classification set.

Runs the shared spec in `decision_config_v2.json` against both engines, measures
latency, scores agreement, and writes REPORT.md.

Budget: jev (TypeSafe) runs on a ~$10 credit, so this makes exactly TWO jev
System One calls total — one batched `.map()` over all cases, and one single
`.decide()` for a non-batched latency sample. ai_decide runs on Databricks
compute (no jev credit) so it is measured per-case and batched.

Usage:
    .venv/bin/python report_compare.py            # both engines (needs .env key)
    .venv/bin/python report_compare.py --ai-only  # skip jev, spend no credit
"""

from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

from decision import (
    check_expected,
    coerce_ai_decide,
    load_config,
    to_ai_decide_questions,
    to_pydantic_model,
)

load_dotenv()

PROFILE = "FEVM_SERVERLESS_STABLE"
CONFIG = "decision_config_v2.json"
AI_ONLY = "--ai-only" in sys.argv

cfg = load_config(CONFIG)
QUESTIONS_JSON = to_ai_decide_questions(cfg)
CASES = cfg["cases"]
FIELDS = [q["name"] for q in cfg["questions"]]
SCORE_FIELDS = {q["name"] for q in cfg["questions"] if q["kind"] == "score"}


def sql_lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def cli_query(sql: str) -> list[dict]:
    proc = subprocess.run(
        ["databricks", "experimental", "aitools", "tools", "query", sql, "--profile", PROFILE],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"CLI failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


# --- ai_decide: per-case (latency) ----------------------------------------

ai_results: dict[str, dict] = {}
ai_latencies: list[float] = []
print("ai_decide: per-case ...")
for c in CASES:
    sql = f"SELECT ai_decide({sql_lit(c['state'])}, {sql_lit(QUESTIONS_JSON)}) AS decision"
    t0 = time.perf_counter()
    rows = cli_query(sql)
    dt = time.perf_counter() - t0
    ai_latencies.append(dt)
    ai_results[c["id"]] = coerce_ai_decide(json.loads(rows[0]["decision"]), cfg)
    print(f"  {c['id']:30} {dt:6.2f}s  {ai_results[c['id']]}")

# --- ai_decide: batched throughput (one CLI call, N rows) ------------------

print("ai_decide: batched (1 query, all rows) ...")
values = ", ".join(f"({sql_lit(c['id'])}, {sql_lit(c['state'])})" for c in CASES)
batch_sql = (
    f"SELECT id, ai_decide(state, {sql_lit(QUESTIONS_JSON)}) AS decision "
    f"FROM VALUES {values} AS t(id, state)"
)
t0 = time.perf_counter()
batch_rows = cli_query(batch_sql)
ai_batch_total = time.perf_counter() - t0
print(f"  {len(batch_rows)} rows in {ai_batch_total:.2f}s "
      f"({ai_batch_total / len(batch_rows):.2f}s/item)")

# --- jev: 2 calls total (map + 1 single) -----------------------------------

jev_results: dict[str, dict] = {}
jev_single_latency = None
jev_map_total = None
jev_calls = 0
if not AI_ONLY:
    import jev

    Model = to_pydantic_model(cfg, "TicketClassification")

    def classify(item):  # noqa: ANN001
        """{{ item }}"""
        raise NotImplementedError

    classify.__annotations__ = {"item": str, "return": Model}
    classify = jev.fn(classify)

    states = [c["state"] for c in CASES]

    print("jev: batched .map() [1 credit call] ...")
    t0 = time.perf_counter()
    mapped = classify.map(states)
    jev_map_total = time.perf_counter() - t0
    for c, m in zip(CASES, mapped, strict=True):
        jev_results[c["id"]] = m.model_dump()
    print(f"  {len(states)} items in {jev_map_total:.2f}s "
          f"({jev_map_total / len(states):.2f}s/item)")

    print("jev: single .decide() [1 credit call] ...")
    t0 = time.perf_counter()
    _ = jev.decide(states[0], Model)
    jev_single_latency = time.perf_counter() - t0
    jev_calls = 2
    print(f"  single call {jev_single_latency:.2f}s")


# --- scoring ---------------------------------------------------------------

def field_agreement() -> dict:
    """Per-field agreement between ai_decide and jev across cases."""
    out = {}
    for f in FIELDS:
        exact = within1 = 0
        for c in CASES:
            a, j = ai_results[c["id"]][f], jev_results[c["id"]][f]
            if a == j:
                exact += 1
                within1 += 1
            elif f in SCORE_FIELDS and abs(a - j) <= 1:
                within1 += 1
        out[f] = (exact, within1, len(CASES))
    return out


ai_pass = {c["id"]: check_expected(ai_results[c["id"]], c["expected"]) for c in CASES}
jev_pass = (
    {c["id"]: check_expected(jev_results[c["id"]], c["expected"]) for c in CASES}
    if not AI_ONLY else {}
)


# --- report ----------------------------------------------------------------

def md_cell(d: dict, f: str) -> str:
    v = d[f]
    return str(v)


lines: list[str] = []
w = lines.append
w(f"# ai_decide vs TypeSafe jev — classification comparison\n")
w(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} · "
  f"profile `{PROFILE}` · {len(CASES)} cases × {len(FIELDS)} questions_\n")

w("## Setup\n")
w(f"- **Spec**: `{CONFIG}` — {len(FIELDS)} questions "
  f"({sum(q['kind']=='choice' for q in cfg['questions'])} choice, "
  f"{sum(q['kind']=='noul' for q in cfg['questions'])} noul, "
  f"{len(SCORE_FIELDS)} score), long-form support content (~150–200 words/case).")
w(f"- **ai_decide**: Databricks SQL on `{PROFILE}` (serverless warehouse).")
w(f"- **jev**: TypeSafe System One via `jev` ({jev_calls} credit calls total — "
  f"1 batched map + 1 single).\n" if not AI_ONLY else "- **jev**: skipped (--ai-only).\n")

# Results table (ai_decide)
w("## Results — ai_decide\n")
w("| case | " + " | ".join(FIELDS) + " | expected? |")
w("|" + "---|" * (len(FIELDS) + 2))
for c in CASES:
    row = ai_results[c["id"]]
    ok = "✅" if not ai_pass[c["id"]] else "❌ " + "; ".join(ai_pass[c["id"]])
    w(f"| {c['id']} | " + " | ".join(md_cell(row, f) for f in FIELDS) + f" | {ok} |")
w("")

if not AI_ONLY:
    w("## Results — jev\n")
    w("| case | " + " | ".join(FIELDS) + " | expected? |")
    w("|" + "---|" * (len(FIELDS) + 2))
    for c in CASES:
        row = jev_results[c["id"]]
        ok = "✅" if not jev_pass[c["id"]] else "❌ " + "; ".join(jev_pass[c["id"]])
        w(f"| {c['id']} | " + " | ".join(md_cell(row, f) for f in FIELDS) + f" | {ok} |")
    w("")

    # Agreement
    w("## Agreement (ai_decide vs jev)\n")
    w("| field | exact | within ±1 (scores) |")
    w("|---|---|---|")
    agg = field_agreement()
    tot_exact = tot = 0
    for f in FIELDS:
        e, w1, n = agg[f]
        tot_exact += e
        tot += n
        extra = f"{w1}/{n}" if f in SCORE_FIELDS else "—"
        w(f"| {f} | {e}/{n} | {extra} |")
    w(f"\n**Overall exact agreement: {tot_exact}/{tot} "
      f"({100*tot_exact/tot:.0f}%)** across all fields and cases.\n")

# Performance
w("## Performance\n")
w("| metric | ai_decide | jev |")
w("|---|---|---|")
w(f"| per-call latency (end-to-end) | {statistics.median(ai_latencies):.2f}s median, "
  f"{min(ai_latencies):.2f}–{max(ai_latencies):.2f}s range"
  + (f" | {jev_single_latency:.2f}s |" if not AI_ONLY else " | — |"))
w(f"| batched throughput | {ai_batch_total/len(CASES):.2f}s/item "
  f"({ai_batch_total:.2f}s / {len(CASES)}) "
  + (f"| {jev_map_total/len(CASES):.2f}s/item ({jev_map_total:.2f}s / {len(CASES)}) |"
     if not AI_ONLY else "| — |"))
w("\n_Notes: ai_decide per-call latency includes Databricks CLI + warehouse "
  "round-trip overhead, not pure engine time. jev latency is the SDK call "
  "end-to-end. Batched rows amortize per-call overhead on both sides._\n")

w("## Cost\n")
if not AI_ONLY:
    w(f"- jev: **{jev_calls} System One calls** total "
      f"({len(CASES)} items via 1 batched map + 1 single). Batching is the "
      f"budget lever — `.map()` classifies all {len(CASES)} cases in one call.")
w("- ai_decide: Databricks DBUs on the serverless warehouse (no jev credit).\n")

report = "\n".join(lines)
with open("REPORT.md", "w") as fh:
    fh.write(report)
print("\nwrote REPORT.md")
