# ai_decide vs TypeSafe jev — classification comparison

_Generated 2026-10-01T07:49:54+00:00 · profile `FEVM_SERVERLESS_STABLE` · 6 cases × 6 questions_

## Setup

- **Spec**: `decision_config_v2.json` — 6 questions (2 choice, 2 noul, 2 score), long-form support content (~150–200 words/case).
- **ai_decide**: Databricks SQL on `FEVM_SERVERLESS_STABLE` (serverless warehouse).
- **jev**: TypeSafe System One via `jev` (2 credit calls total — 1 batched map + 1 single).

## Results — ai_decide

| case | category | sentiment | is_urgent | requires_human | priority | churn_risk | expected? |
|---|---|---|---|---|---|---|---|
| billing_double_charge_angry | billing | negative | True | True | 5 | 5 | ✅ |
| technical_prod_outage | technical | negative | True | True | 5 | 4 | ✅ |
| account_lockout | account_access | neutral | True | True | 3 | 2 | ❌ is_urgent: got True, want False |
| sales_enterprise_inquiry | sales | positive | True | True | 4 | 1 | ❌ is_urgent: got True, want False; priority: got 4, want <= 3 |
| product_feedback_feature | product_feedback | positive | False | False | 1 | 1 | ✅ |
| legal_gdpr_erasure | legal_compliance | negative | True | True | 4 | 3 | ✅ |

## Results — jev

| case | category | sentiment | is_urgent | requires_human | priority | churn_risk | expected? |
|---|---|---|---|---|---|---|---|
| billing_double_charge_angry | billing | negative | False | True | 4 | 5 | ❌ is_urgent: got False, want True |
| technical_prod_outage | technical | negative | True | True | 5 | 4 | ✅ |
| account_lockout | account_access | neutral | False | True | 3 | 2 | ✅ |
| sales_enterprise_inquiry | sales | neutral | False | True | 3 | 2 | ✅ |
| product_feedback_feature | product_feedback | positive | False | False | 1 | 1 | ✅ |
| legal_gdpr_erasure | legal_compliance | neutral | False | True | 3 | 2 | ❌ is_urgent: got False, want True |

## Agreement (ai_decide vs jev)

| field | exact | within ±1 (scores) |
|---|---|---|
| category | 6/6 | — |
| sentiment | 4/6 | — |
| is_urgent | 2/6 | — |
| requires_human | 6/6 | — |
| priority | 3/6 | 6/6 |
| churn_risk | 4/6 | 6/6 |

**Overall exact agreement: 25/36 (69%)** across all fields and cases.

## Performance

| metric | ai_decide | jev |
|---|---|---|
| per-call latency (end-to-end) | 15.53s median, 12.71–21.50s range | 0.28s |
| batched throughput | 7.97s/item (47.81s / 6) | 0.09s/item (0.55s / 6) |

_Notes: ai_decide per-call latency includes Databricks CLI + warehouse round-trip overhead, not pure engine time. jev latency is the SDK call end-to-end. Batched rows amortize per-call overhead on both sides._

## Cost

- jev: **2 System One calls** total (6 items via 1 batched map + 1 single). Batching is the budget lever — `.map()` classifies all 6 cases in one call.
- ai_decide: Databricks DBUs on the serverless warehouse (no jev credit).
