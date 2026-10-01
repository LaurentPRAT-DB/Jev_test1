"""Run the SAME shared decision spec against TypeSafe jev (Python).

Reads `decision_config.json`, projects it onto a pydantic model, and calls
`jev.decide(state, Model)` per case — the identical questions and cases that
`test_ai_decide.py` sends to Databricks ai_decide. Compare the two runs to see
how close ai_decide is to the jev model.

Skipped unless TYPESAFE_API_KEY is set (jev makes a live System One call).

Run:
    TYPESAFE_API_KEY=... .venv/bin/python -m pytest test_jev_decision.py -v
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from decision import check_expected, load_config, to_pydantic_model

load_dotenv()  # pull TYPESAFE_API_KEY from the gitignored .env

pytestmark = pytest.mark.skipif(
    not os.environ.get("TYPESAFE_API_KEY"),
    reason="set TYPESAFE_API_KEY to run the live jev comparison",
)

CFG = load_config()
Decision = to_pydantic_model(CFG)


@pytest.mark.parametrize("case", CFG["cases"], ids=[c["id"] for c in CFG["cases"]])
def test_jev_case(case: dict):
    import jev

    result = jev.decide(case["state"], Decision).model_dump()
    fails = check_expected(result, case["expected"])
    assert not fails, f"{case['id']}: {result} -> " + "; ".join(fails)
