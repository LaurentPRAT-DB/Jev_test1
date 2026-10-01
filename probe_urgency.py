"""Reveal the raw is_urgent noul probability from BOTH engines.

coerce uses the same 0.5 threshold for both, so any disagreement must come from
the engines emitting different probabilities — this prints them to prove it.

jev cost: 1 batched System One call (all cases, prefixed questions like .map()).
ai_decide: free (Databricks DBUs), one batched SQL.
"""

from __future__ import annotations

import os
import json
import subprocess

from dotenv import load_dotenv

from decision import load_config

load_dotenv()
PROFILE = os.environ.get("DATABRICKS_PROFILE", "DEFAULT")
cfg = load_config("decision_config_v2.json")
cases = cfg["cases"]
q = next(x for x in cfg["questions"] if x["name"] == "is_urgent")
INSTR = q["instructions"]
CRIT = q["criteria"]


def sql_lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


# ai_decide: one batched SQL, is_urgent only
questions_json = json.dumps({"is_urgent": {"type": "noul", "instructions": INSTR, "criteria": CRIT}})
values = ", ".join(f"({sql_lit(c['id'])}, {sql_lit(c['state'])})" for c in cases)
sql = (f"SELECT id, ai_decide(state, {sql_lit(questions_json)}) AS d "
       f"FROM VALUES {values} AS t(id, state)")
proc = subprocess.run(
    ["databricks", "experimental", "aitools", "tools", "query", sql, "--profile", PROFILE],
    capture_output=True, text=True, timeout=300,
)
if proc.returncode != 0:
    raise RuntimeError(proc.stderr)
ai_prob = {}
for row in json.loads(proc.stdout):
    d = json.loads(row["d"])
    ai_prob[row["id"]] = d["response"]["answers"]["is_urgent"]["probability"]

# jev: one batched System One call via typesafe_sdk (prefixed questions)
from typesafe_sdk import Noul, TypeSafeClient

client = TypeSafeClient()
batched = {f"{i}:is_urgent": Noul(instructions=f"For the item at index {i} in the state array: {INSTR}",
                                  criteria=CRIT) for i in range(len(cases))}
resp = client.system_one(state=[c["state"] for c in cases], questions=batched)
jev_prob = {cases[i]["id"]: resp.nouls[f"{i}:is_urgent"].noul for i in range(len(cases))}

print(f"{'case':30} {'ai_decide p':>12} {'jev p':>8}  {'ai>=.5':>6} {'jev>=.5':>7}")
for c in cases:
    a, j = ai_prob[c["id"]], jev_prob[c["id"]]
    print(f"{c['id']:30} {a:12.3f} {j:8.3f}  {str(a>=0.5):>6} {str(j>=0.5):>7}")
