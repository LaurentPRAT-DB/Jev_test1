"""Run the shared decision spec against Databricks `ai_decide` (SQL).

Reads `decision_config.json`, builds one `ai_decide` call per case, runs it on
the SQL warehouse via the Databricks CLI, coerces the raw answer with the SAME
rules jev uses, and asserts against the per-case expected values.

The identical spec runs against TypeSafe jev in `test_jev_decision.py`, so the
two engines are compared on exactly the same questions and cases.

Env:
    DATABRICKS_PROFILE   CLI profile (default: FEVM_SERVERLESS_STABLE)

Run:
    .venv/bin/python -m pytest test_ai_decide.py -v
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from decision import (
    coerce_ai_decide,
    check_expected,
    load_config,
    to_ai_decide_questions,
)

PROFILE = os.environ.get("DATABRICKS_PROFILE", "FEVM_SERVERLESS_STABLE")
CFG = load_config()
QUESTIONS_JSON = to_ai_decide_questions(CFG)


def _sql_literal(s: str) -> str:
    """Single-quoted SQL string literal (escape embedded single quotes)."""
    return "'" + s.replace("'", "''") + "'"


def run_ai_decide(state: str) -> dict:
    """Call ai_decide for one state via the Databricks CLI; return raw answer dict."""
    sql = (
        f"SELECT ai_decide({_sql_literal(state)}, "
        f"{_sql_literal(QUESTIONS_JSON)}) AS decision"
    )
    proc = subprocess.run(
        ["databricks", "experimental", "aitools", "tools", "query", sql, "--profile", PROFILE],
        capture_output=True, text=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"CLI failed: {proc.stderr.strip()}")
    rows = json.loads(proc.stdout)
    return json.loads(rows[0]["decision"])


@pytest.mark.parametrize("case", CFG["cases"], ids=[c["id"] for c in CFG["cases"]])
def test_ai_decide_case(case: dict):
    raw = run_ai_decide(case["state"])
    result = coerce_ai_decide(raw, CFG)
    fails = check_expected(result, case["expected"])
    assert not fails, f"{case['id']}: {result} -> " + "; ".join(fails)
