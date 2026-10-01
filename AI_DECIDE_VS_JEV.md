# ai_decide vs TypeSafe jev — when to use which

Both run the **same TypeSafe System One engine** (identical `noul` / `choice` /
`score` primitives, identical request/response shape). So this is not a quality
decision — on hard labels they agree strongly (category/requires_human 6/6 in our
tests; scores within ±1). The choice is about **where the data lives, latency,
scale, and operations.** The single biggest factor is: **is the data already in
Databricks?**

---

## TL;DR

| You have… | Use | Why |
|---|---|---|
| Data already in a **Delta table / Unity Catalog** | **ai_decide** | Decide in-place with SQL; no export, no API fan-out, no new service |
| A **real-time / per-event** path (queue consumer, request handler, app) | **jev** | ~0.3s latency floor vs ~6s warehouse spin-up; low per-call overhead |
| **Millions of rows** to classify offline, already in the lakehouse | **ai_decide** | One distributed job scales with cluster; no HTTP rate limits |
| **Python app** needing typed objects, mocking, per-call model/threshold | **jev** | Pydantic return types, test seams, `jev.decide` flexibility |
| Results must **land back in tables** with lineage / governance | **ai_decide** | Output is a column; stays in UC, auditable, joins to everything |

---

## They are the same model

- Same three primitives; same `state` + `questions`; same answer fields
  (`probability` / `choice`+`probabilities`+`confidence` / `score`+`legend`+…).
- `jev` adds a **Python/pydantic wrapper** (typed models, coercion, `.map`,
  mock seam). `ai_decide` is a **SQL function** returning raw `VARIANT`.
- Measured agreement on hard labels is high; the only notable divergence we saw
  was `noul` **calibration** on borderline questions (ai_decide runs slightly
  hotter), which is a threshold-tuning matter, not a capability gap.

So pick on **delivery and data gravity**, not accuracy.

---

## The deciding factor: where is the data?

### Data already in Databricks → ai_decide

If the rows live in a Delta table, `ai_decide` is almost always the right call:

```sql
-- classify in place; result is a column, joins to everything, stays governed
CREATE TABLE triaged AS
SELECT *,
       ai_decide(body, :questions):response.answers.category.choice      AS category,
       ai_decide(body, :questions):response.answers.is_urgent.probability AS urgency_p
FROM support_tickets;
```

Advantages:
- **No data movement.** No export to an external API, no egress, no PII leaving the lakehouse boundary.
- **No fan-out orchestration.** One SQL job vs. a client looping millions of HTTP calls (and handling retries, backoff, rate limits, partial failures).
- **Scales with the cluster.** It's a distributed op; add workers to raise throughput — no per-request ceiling.
- **Results are first-class data.** Output columns join to the source, feed BI/pipelines, carry **Unity Catalog lineage and governance**, and are reproducible/auditable.
- **One platform.** No second service to deploy, authenticate, monitor, or bill separately. Governed by the same UC permissions.
- **Composability.** Combine with `ai_query`, window functions, joins, MVs, DLT — the decision is just SQL in a bigger pipeline.

### Data outside Databricks, or decided at the edge → jev

If the content arrives as events (queue, webhook, request) and you act *now*:
- **Low latency**: ~0.3s per call vs ~6s warehouse fixed cost — jev wins decisively for small/single items.
- **Typed ergonomics**: pydantic return model, per-call `model`/`bool_threshold`, `.map()` batching, mock seam for tests.
- **No warehouse** needed; runs anywhere Python runs.

Pushing per-event data *into* Databricks just to run `ai_decide` adds a round-trip and a warehouse spin-up — jev is simpler and faster there.

---

## Performance (measured, this environment)

Small serverless warehouse, 1 noul, via CLI:

| metric | ai_decide | jev |
|---|---|---|
| fixed cost / call | ~6s (incl. CLI; a warm Spark job pays less) | ~0.3s |
| marginal / row | ~0.52s (~1.9 rows/s on this small warehouse) | ~0.09s (~11 rows/s, batched `.map`) |
| crossover | none observed 1→100k on this warehouse | jev faster at every N here |

**Read this carefully:** ai_decide's ~1.9 rows/s is the *small-warehouse* rate —
it did not add parallelism at these sizes. ai_decide is distributed, so its
marginal per-row **drops ~linearly with cluster width**. The crossover is
therefore `0.52s / parallelism < 0.09s` → ai_decide beats jev's per-row rate
once the cluster is **~6×+ wider** than this test, **and** N is large enough to
amortize the fixed cost. jev's rate is flat and also bounded by **API
concurrency / rate limits / payload caps** at sustained high volume.

So: **latency → jev; raw throughput at scale → ai_decide on a sized cluster.**

---

## Cost

- **ai_decide**: Databricks DBUs on the warehouse/cluster. No separate vendor; scale cost = cluster size × time. Already-in-UC data incurs no egress.
- **jev**: TypeSafe credits per System One call. Batch with `.map()` to amortize; watch rate limits and per-call payload size at volume.

---

## Operational trade-offs

| dimension | ai_decide | jev |
|---|---|---|
| data movement | none (in-lakehouse) | content leaves to the API |
| governance / lineage | native Unity Catalog | your app's responsibility |
| orchestration at scale | one SQL/Spark job | client-side fan-out + rate-limit handling |
| latency floor | warehouse spin-up (~seconds) | ~0.3s |
| typed outputs / mocking | parse `VARIANT` yourself | pydantic models + mock seam |
| per-question / dynamic thresholds | threshold the raw `probability` in SQL/code | raw `p` + code (global `bool_threshold` only) |
| platform footprint | nothing new (it's SQL) | a service/SDK to run + auth |
| availability | needs DBR 15.4+, select regions, not SQL Classic | any Python runtime + API key |

---

## Decision checklist

Choose **ai_decide** if most are true:
- [ ] The data is already in Delta / Unity Catalog.
- [ ] You're doing batch/offline classification (not a request path).
- [ ] Volume is high and you can size a cluster.
- [ ] Results should stay in tables with lineage/governance.
- [ ] You want zero new services and SQL-native composition.

Choose **jev** if most are true:
- [ ] Decisions happen per-event / in real time (queue, webhook, app).
- [ ] Latency matters (sub-second per item).
- [ ] The content originates outside Databricks.
- [ ] You want typed pydantic results, mocking, per-call model/threshold control.

**Hybrid is valid:** jev on the hot path for immediate routing, ai_decide for
the bulk backfill/re-scoring of the same content once it lands in the lakehouse —
same engine, so the semantics match.

---

_Based on this repo's tests: `decision.py`, `REPORT.md` (agreement + latency),
`examples/sla_queue/` (routing), `examples/sla_queue/measure_scaling.py`
(throughput fit). Both engines verified live against the same shared specs._
