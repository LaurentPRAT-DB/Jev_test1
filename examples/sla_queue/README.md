# SLA-aware ticket routing (batch from a queue)

Worked example of the pattern in [`../../CONFIG_GUIDE.md`](../../CONFIG_GUIDE.md) §7–8:

> The model judges **content only** → one SLA-blind probability `p` per ticket.
> The **SLA** is business metadata applied as a **per-ticket threshold** in code.
> Identical content under different SLA → same `p`, different route.

## Why this shape

- **One engine call per batch.** Content is queried once; `p` is reusable.
- **SLA never reaches the model.** Criticality is a deterministic, auditable
  business rule — change the cuts or add a tier without re-querying.
- **Per-question / per-ticket cuts live in code**, not in `jev`'s global
  `bool_threshold`. We keep the raw `p` and threshold it per ticket.

## Files

| file | role |
|---|---|
| `sla_config.json` | the one noul question (content-only) + per-SLA cut points |
| `tickets.py` | stand-in message queue; `pull_batch()` (T1/T2 are identical content, different SLA) |
| `engine.py` | raw `p` per body — 3 backends: `stub` (offline), `jev`, `ai_decide` |
| `router.py` | pure `route(sla, p, cfg) -> (verdict, action)`; no API |
| `run.py` | pull → one engine call → per-SLA route → print |
| `test_router.py` | offline unit tests: same `p` routes differently by SLA |

## Run

```sh
# offline, no API, no credit (keyword-heuristic stub stands in for the model)
../../.venv/bin/python run.py

# live TypeSafe jev — ONE batched System One call (uses ../../.env key)
../../.venv/bin/python run.py --engine jev

# live Databricks ai_decide — ONE batched SQL call on your-profile
../../.venv/bin/python run.py --engine ai_decide

# unit tests (offline)
../../.venv/bin/python -m pytest test_router.py -q
```

## What it shows (stub output)

```
id   sla          p    cut(crit/rev)  verdict   route
T1   enterprise  0.74  0.30/0.15      CRITICAL  page on-call
T2   free        0.74  0.80/0.50      REVIEW    human queue     <- same text as T1
T4   free        0.90  0.80/0.50      CRITICAL  page on-call
T6   business    0.34  0.50/0.30      REVIEW    human queue
```

T1 and T2 are the **same ticket text** → the **same `p` = 0.74** → different
outcome purely from the SLA cut. Enterprise escalates on a weaker signal
(critical ≥ 0.30); free needs a strong signal (critical ≥ 0.80) and otherwise
sends to human review.

## Tuning levers (all config / code, no re-query)

- **Sharper boundary per question** → tighten `question.instructions` / `criteria` in `sla_config.json` (model side).
- **Criticality per tier** → edit `sla_cuts` (critical/review per SLA).
- **New tier** → add a `sla_cuts` entry; no model change.
- **Three-way routing** → already: `CRITICAL` / `REVIEW` / `ROUTINE` from the two cut points.

> Budget: `jev` runs on a ~$10 credit. `run.py --engine jev` makes exactly **one**
> batched call for the whole batch. Default `stub` spends nothing.
