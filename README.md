# Jev_test1 — Databricks `ai_decide` vs TypeSafe `jev`

Testing ground for [`jev`](https://pypi.org/project/jev/) — a decorator that compiles
Python function definitions into TypeSafe **System One** structured-decision queries
(it generates no text; it answers typed questions — yes/no probabilities, choices,
scores — about a state in one parallel call).

The headline finding: **Databricks SQL [`ai_decide`](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_decide)
and `jev` are the same System One engine** — identical `noul` / `choice` / `score`
primitives, identical request/response shape. So the real question isn't *which is
smarter*, it's **where your data lives** and **how it needs to scale**.

> 📖 **Read the write-up:** [*The same model, two front doors — Databricks `ai_decide` vs TypeSafe `jev`*](https://laurentprat-db.github.io/Jev_test1/medium_article_hybrid.html)

![The same model, two front doors](docs/images/hero.png)

## What's in here

| Path | What |
|------|------|
| `test_jev.py` | Offline jev unit tests (mock seam, state builder, field validation) |
| `decision.py` | Neutral decision spec → `ai_decide` (SQL) and `jev` (pydantic) projections + shared coercion |
| `decision_config.json`, `decision_config_v2.json` | Shared specs (simple + 6-question classification) |
| `test_ai_decide.py`, `test_jev_decision.py` | Same spec run on both engines |
| `report_compare.py` → `REPORT.md` | Agreement + latency benchmark |
| `probe_urgency.py` | Raw `noul` probabilities, both engines |
| `examples/sla_queue/` | SLA-aware routing: content-only probability + per-ticket threshold in code |
| `CONFIG_GUIDE.md` | How to configure state, schema, expected answers, noul thresholds/intervals |
| `AI_DECIDE_VS_JEV.md` | Full when-to-use decision doc |
| `docs/` | A Medium article write-up (published via GitHub Pages) |

## Setup

```sh
uv venv --python 3.14 .venv
uv pip install -p .venv jev pytest
```

## Tests

```sh
# Offline — no key, no network (mock seam, state builder, validation)
.venv/bin/python -m pytest test_jev.py -v

# Offline — SLA routing logic (same probability routes differently per SLA)
.venv/bin/python -m pytest examples/sla_queue/test_router.py -q

# Live Databricks ai_decide (needs a SQL warehouse profile; DBR 15.4+)
.venv/bin/python -m pytest test_ai_decide.py -v

# Live TypeSafe jev (needs TYPESAFE_API_KEY in .env)
.venv/bin/python -m pytest test_jev_decision.py -v

# Full comparison + benchmark -> REPORT.md
.venv/bin/python report_compare.py        # --ai-only to skip jev / spend no credit
```

The SLA example runs offline by default and against either engine live:

```sh
cd examples/sla_queue
python run.py                 # offline keyword-heuristic stub, no credit
python run.py --engine jev    # 1 batched TypeSafe call
python run.py --engine ai_decide
```

## Benchmark results

Same spec, both engines — six long-form support tickets, six questions each.

**Agreement: 25/36 (69%) exact.** But the structure matters:

- **Hard labels agreed perfectly** — `category` 6/6, `requires_human` 6/6.
- **Scores agreed within ±1 on every case** (6/6) — same ranking, sampling noise.
- **Only real divergence: the `is_urgent` noul.** `ai_decide` runs *hotter* on urgency (p ≈ 0.80–0.99), `jev` more *conservative* (p ≈ 0.20–0.29). Same 0.5 threshold applied to both, so this is **calibration**, not a capability gap — and jev's borderline values sit in the "route to human review" band. Fixable with per-engine threshold tuning.

**Performance (small FEVM serverless warehouse, 1 noul):**

| metric | ai_decide | jev |
|---|---|---|
| per-call latency (end-to-end) | ~15.5s (incl. CLI + warehouse) | ~0.3s |
| fit (batched) | ~6s fixed + 0.52s/row (~1.9 rows/s) | ~0.09s/item (~11 rows/s) |

On this small warehouse, **jev was faster at every batch size from 1 to 100,000 — no crossover.**

## Conclusion — data residency and scaling decide it

Because the two are the same model, the choice is operational, and it comes down to two axes:

### 1. Data residency (where the data lives) — the primary factor

- **Data already in Delta / Unity Catalog → `ai_decide`.** Classify **in place** with SQL:
  no export, no egress, no PII leaving the lakehouse boundary; results land as
  **governed columns with Unity Catalog lineage**; one SQL job instead of orchestrating
  millions of client-side API calls with retries and rate-limit handling.
- **Data arriving as events / outside Databricks → `jev`.** ~0.3s latency floor, typed
  Pydantic objects, mock seam, per-call model + threshold. Pushing per-event data into a
  warehouse just to call `ai_decide` only adds a round-trip.

### 2. Scaling capability (how throughput grows)

- **`jev`** has a low per-call floor (~0.3s) and a flat ~11 rows/s batched rate, but that
  rate is **bounded by API concurrency, rate limits, and payload caps** at sustained volume,
  and every item is an HTTP round-trip.
- **`ai_decide`** carries higher fixed cost (warehouse) but is a **distributed SQL op**: its
  per-row cost drops ~linearly with cluster width and has **no per-request ceiling**. The
  crossover is `0.52s / parallelism < 0.09s` → `ai_decide` wins once the cluster is ~6×+
  wider than this small-warehouse test **and** the batch is large enough to amortize the
  fixed cost. At lakehouse scale (millions of rows at rest) it's one job you widen, not a
  fan-out you babysit.

**Rule of thumb:**

- Real-time / per-event / data at the edge → **`jev`**.
- Batch over data already at rest in Databricks, especially at high volume → **`ai_decide`**.
- Same engine, so a **hybrid** is safe: `jev` on the hot path, `ai_decide` for the bulk
  backfill once the content lands in the lakehouse.

See **[AI_DECIDE_VS_JEV.md](AI_DECIDE_VS_JEV.md)** for the full decision matrix and
**[CONFIG_GUIDE.md](CONFIG_GUIDE.md)** for configuring states, schemas, expected answers,
and noul thresholds.

## Real jev calls

Set `TYPESAFE_API_KEY` in `.env` and make a decorated function body-less (`...`);
calling it then queries System One. See [console.typesafe.ai](https://console.typesafe.ai).
```
