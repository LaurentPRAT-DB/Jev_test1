"""Shared decision spec → two backends.

`decision_config.json` is the single source of truth: a neutral list of
questions (bool / choice / score) plus test cases. This module projects that
one spec onto both engines so the *identical* decision runs against each:

- `to_ai_decide_questions(cfg)` -> the JSON string Databricks `ai_decide` takes.
- `coerce_ai_decide(raw, cfg)`  -> raw ai_decide VARIANT -> typed Python dict,
  applying the SAME coercion jev applies (noul>=0.5 -> bool, choice -> label,
  score -> ge + round(expected)).
- `to_pydantic_model(cfg)`      -> a pydantic model whose fields map 1:1 onto
  the questions, i.e. a drop-in `jev.decide(state, Model)` return type.

Both engines are TypeSafe System One underneath; only the client ergonomics
differ. See memory `ai-decide-equivalence`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, create_model

CONFIG_PATH = Path(__file__).with_name("decision_config.json")


def load_config(path: Path | str = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


# --- ai_decide projection -------------------------------------------------


def to_ai_decide_questions(cfg: dict[str, Any]) -> str:
    """Build the `questions` JSON string for Databricks `ai_decide`."""
    questions: dict[str, Any] = {}
    for q in cfg["questions"]:
        kind = q["kind"]
        if kind in ("bool", "noul"):
            entry: dict[str, Any] = {"type": "noul", "instructions": q["instructions"]}
            if "criteria" in q:
                entry["criteria"] = q["criteria"]
        elif kind == "choice":
            entry = {"type": "choice", "instructions": q["instructions"], "criteria": q["options"]}
        elif kind == "score":
            entry = {"type": "score", "instructions": q["instructions"], "criteria": q["levels"]}
        else:
            raise ValueError(f"unknown kind {kind!r} for question {q['name']!r}")
        questions[q["name"]] = entry
    return json.dumps(questions)


def coerce_ai_decide(raw: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Raw ai_decide answers -> typed dict, matching jev's coercion exactly."""
    if raw.get("error_message"):
        raise RuntimeError(f"ai_decide error: {raw['error_message']}")
    answers = raw["response"]["answers"]
    out: dict[str, Any] = {}
    for q in cfg["questions"]:
        name, kind, a = q["name"], q["kind"], answers[q["name"]]
        if kind in ("bool", "noul"):
            out[name] = a["probability"] >= 0.5
        elif kind == "choice":
            out[name] = a["choice"]
        elif kind == "score":
            # ai_decide score is in [0, n_levels-1]; jev int coercion is
            # lo + round(expected). legend is 0-indexed, so this lines up.
            out[name] = int(q["ge"]) + int(round(a["score"]))
    return out


# --- jev / pydantic projection --------------------------------------------


def to_pydantic_model(cfg: dict[str, Any], name: str = "Decision") -> type[BaseModel]:
    """A pydantic model matching the spec — the jev.decide(state, Model) type."""
    fields: dict[str, Any] = {}
    for q in cfg["questions"]:
        kind = q["kind"]
        if kind in ("bool", "noul"):
            fields[q["name"]] = (bool, Field(description=q["instructions"]))
        elif kind == "choice":
            lit = Literal[tuple(q["options"].keys())]  # type: ignore[valid-type]
            fields[q["name"]] = (lit, Field(description=q["instructions"]))
        elif kind == "score":
            fields[q["name"]] = (
                int,
                Field(
                    ge=q["ge"], le=q["le"], description=q["instructions"],
                    json_schema_extra={"levels": q["levels"]},
                ),
            )
    return create_model(name, **fields)


def check_expected(result: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Return a list of mismatch strings (empty = pass). Generic over fields.

    Expected keys:
      - `<field>`        exact match (choice label or bool)
      - `<field>_min`    result[field] >= value (score lower bound)
      - `<field>_max`    result[field] <= value (score upper bound)
    """
    fails: list[str] = []
    for key, want in expected.items():
        if key.endswith("_min"):
            field = key[:-4]
            if result[field] < want:
                fails.append(f"{field}: got {result[field]}, want >= {want}")
        elif key.endswith("_max"):
            field = key[:-4]
            if result[field] > want:
                fails.append(f"{field}: got {result[field]}, want <= {want}")
        else:
            if result[key] != want:
                fails.append(f"{key}: got {result[key]!r}, want {want!r}")
    return fails
