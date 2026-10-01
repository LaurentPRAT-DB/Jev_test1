# Configuring the decision model — input, schema, expected answers

This guide explains how to configure a TypeSafe System One decision — the same
spec runs on **TypeSafe jev** (Python) and **Databricks `ai_decide`** (SQL),
because both wrap the identical engine. It covers four things:

1. **The input** — the `state` you hand the model.
2. **The schema** — the `questions` (the three primitives) that define what to decide.
3. **The expected answers** — how to assert correctness in tests.
4. **The noul interval** — thresholds that control yes / no / "route to a human".

The single source of truth is a neutral JSON config (`decision_config*.json`);
`decision.py` projects it onto each engine. You edit the config, not the engines.

---

## 1. The input: `state`

The `state` is the content the model judges. One decision = one state.

| | jev | ai_decide |
|---|---|---|
| type | any `JSONContent` (str, dict, list) | `STRING` or `VARIANT` |
| plain text | `jev.decide("I was charged twice", Model)` | `ai_decide('I was charged twice', '{...}')` |
| structured | pass a dict; it is JSON-encoded | pass a JSON string, or `parse_json(...)` |

**Framing (jev only).** With `@jev.fn`, the function docstring is a Jinja2
template rendered into the state from the arguments:

```python
@jev.fn
def triage(ticket: str, customer_tier: str) -> Triage:
    """A {{ customer_tier }} customer wrote:

    {{ ticket }}
    """
    ...
```

Rules of thumb for the state:
- Give the model the **whole** relevant content (jev/System One handle long text well — our test cases are ~150–200 words).
- Put context the questions depend on **into** the state (tier, channel, prior history).
- The state carries the facts; the **questions** carry what to decide. Don't bake the decision into the state.

---

## 2. The schema: `questions`

There are **exactly three primitives**. Every field of your decision is one of them.
In the neutral config each question is one object in `questions[]`:

```jsonc
{ "name": "<field>", "kind": "<noul|bool|choice|score>", "instructions": "...", ... }
```

### noul (a.k.a. bool) — a yes/no probability

```jsonc
{
  "name": "is_urgent",
  "kind": "noul",
  "instructions": "Does this require a fast response (hours, not days)?",
  "criteria": {                      // OPTIONAL — instruction alone often suffices
    "true":  "Active blocker, money at risk, deadline",
    "false": "Informational or has a workaround"
  }
}
```

- Returns a single probability in **[0, 1]** = p(yes). **No confidence field** — the probability already encodes certainty.
- Ask **one** thing per noul. Split "angry AND asking for refund" into two nouls, combine in code.
- Phrase so **high = yes**. Avoid inversions ("is free of PII").

### choice — pick one from an **unordered** set

```jsonc
{
  "name": "category",
  "kind": "choice",
  "instructions": "Classify the primary intent.",
  "options": {                       // label -> meaning; order does not matter
    "billing":   "Charges, refunds, invoices",
    "technical": "Bugs, crashes, outages",
    "sales":     "Pricing, plans, purchasing"
  }
}
```

- Returns `choice` (a label) + `probabilities` (full distribution) + `confidence` (how peaked).
- jev caps options at **255**.

### score — rate along an **ordered** spectrum

```jsonc
{
  "name": "priority",
  "kind": "score",
  "instructions": "Operational priority to assign.",
  "levels": ["Very low", "Low", "Medium", "High", "Critical"],  // ORDERED, low -> high
  "ge": 1, "le": 5                   // integer range the level labels map onto
}
```

- Returns `score` (can land **between** levels — a weighted average) + `legend` + `probabilities` + `confidence`.
- `ge`/`le` set the integer scale; `levels` must have exactly `le - ge + 1` entries.
- Coercion: integer field → `ge + round(expected)`; a float field interpolates linearly. jev caps levels at **256**.

**choice vs score:** unordered categories → `choice`; a ranked magnitude → `score`.

### Authoring tips
- Questions are evaluated **in parallel** — adding more barely changes latency, so ask everything you need in one decision; don't drop questions "for speed".
- Keep `instructions` concrete and testable. Use `criteria`/`options`/`levels` to pin boundary cases.
- Start without `criteria` on nouls; add it only if answers improve on your data.

---

## 3. Expected answers (for tests)

Each case pairs a `state` with the answers you expect. The checker
(`decision.check_expected`) understands three key forms:

```jsonc
"expected": {
  "category": "billing",       // choice/bool: EXACT match required
  "is_urgent": true,           // bool: exact
  "priority_min": 4,           // score: result >= 4
  "churn_risk_max": 2          // score: result <= 2
}
```

| field kind | assert with | why |
|---|---|---|
| choice | `"<field>": "<label>"` | labels are discrete; exact is right |
| noul/bool | `"<field>": true/false` | after thresholding |
| score | `"<field>_min"` / `"<field>_max"` | **use bands, not exact** |

**Use score bands.** The model is sampled, so a score can wobble ±1 notch
run-to-run (we observed exactly this). Asserting `priority == 4` is flaky;
`priority_min: 4` is stable and still meaningful. Only pin an exact score when
the level genuinely must be that one.

Leave a field out of `expected` when you don't want to assert it.

---

## 4. The noul interval — controlling yes / no / review

A noul gives a probability; **you** decide where the cutoffs are. This is the
main lever for model behavior on yes/no questions.

### Single threshold (two-way)

Default is **0.5**. Move it based on which error costs more:

| situation | threshold | effect |
|---|---|---|
| yes and no equally easy to act on | **0.5** | balanced |
| false positive expensive (paging, refund, auto-escalate) | **0.8–0.9** | only fire on strong yes |
| false negative expensive (safety, compliance miss) | **0.2–0.3** | fire unless strong no |

- jev: `jev.decide(state, Model, bool_threshold=0.8)` or `@jev.fn(bool_threshold=0.8)` or env `JEV_BOOL_THRESHOLD`.
- ai_decide: returns the raw `probability`; apply the threshold in SQL/Python yourself.

### Interval (three-way: route the uncertain middle to a human)

The recommended pattern for borderline questions is a **band**: act on the
confident ends, send the middle to review.

```
          0.0 ───────── 0.2 ───────────────── 0.8 ───────── 1.0
   verdict:    NO       │       REVIEW         │     YES
```

```python
def route(p, lo=0.2, hi=0.8):
    if p >= hi:  return "yes"
    if p <= lo:  return "no"
    return "review"      # hand to a human
```

Widen the band (e.g. 0.3–0.7) to send more cases to review; narrow it
(0.45–0.55) to automate more and review less.

**This matters for our data.** The `is_urgent` divergence we measured —
ai_decide ~0.80–0.99 vs jev ~0.20–0.29 on account-lockout / sales / legal — is
not a label error: those jev values sit inside the 0.2–0.8 band, i.e. the model
is honestly saying "uncertain, review me," while ai_decide's calibration runs
hotter. A fixed 0.5 bool hides that; the interval surfaces it.

### Making the interval part of the config

To configure behavior per question, add an optional block (consumed by your
routing code, not by the engines):

```jsonc
{
  "name": "is_urgent",
  "kind": "noul",
  "instructions": "...",
  "thresholds": { "yes": 0.8, "no": 0.2 }   // p>=yes -> true; p<=no -> false; else review
}
```

Then coerce a noul to one of `"yes" | "no" | "review"` instead of a bare bool,
and your `expected` can assert the routed verdict. (Score questions can take an
analogous `thresholds` on the numeric scale if you need a review band there too.)

---

## 5. Full example (neutral config → both engines)

```jsonc
// decision_config.json
{
  "questions": [
    { "name": "department", "kind": "choice",
      "instructions": "Which team handles this ticket?",
      "options": { "billing": "Payments", "technical": "Bugs", "sales": "Pricing" } },
    { "name": "is_urgent", "kind": "noul",
      "instructions": "Needs a fast response?",
      "thresholds": { "yes": 0.8, "no": 0.2 } },
    { "name": "severity", "kind": "score",
      "instructions": "Severity of the issue.",
      "levels": ["Trivial","Minor","Moderate","Serious","Critical"], "ge": 1, "le": 5 }
  ],
  "cases": [
    { "id": "double_charge", "state": "I was charged twice and want a refund!",
      "expected": { "department": "billing", "is_urgent": true, "severity_min": 3 } }
  ]
}
```

- `decision.to_ai_decide_questions(cfg)` → the `questions` JSON string for `ai_decide(state, questions)`.
- `decision.to_pydantic_model(cfg)` → the pydantic model for `jev.decide(state, Model)`.
- `decision.coerce_ai_decide(raw, cfg)` → raw VARIANT → the same typed dict jev returns.
- `decision.check_expected(result, expected)` → list of mismatches (empty = pass).

Edit the config; both engines and both test suites pick it up unchanged.

---

## 6. Behavior-tuning checklist

| want to change | lever |
|---|---|
| what gets decided | add/edit `questions` |
| what counts as yes/no | noul `criteria` + `thresholds` (or `bool_threshold`) |
| category boundaries | choice `options` descriptions |
| score meaning / granularity | score `levels`, `ge`, `le` |
| fewer false escalations | raise noul `yes` threshold toward 0.9 |
| catch every edge, accept review load | widen the 0.2–0.8 band |
| test stability on scores | assert `_min`/`_max` bands, not exact |
| context-dependent decisions | put the context into the `state` (jev: via the docstring template) |

---

## 7. Per-question boundaries & realtime routing

Goal: a **sharper boundary decided per question** (not one global cut), driven
by realtime data, so each question can route to its own handler. There are two
boundaries, and they live in different places — keep them separate.

### Two boundaries, two owners

| boundary | owner | scope | lever |
|---|---|---|---|
| **where `p` lands** (the model's own calibration) | the model | **already per-question** | each question's `instructions` + `criteria` |
| **where you cut `p`** into a verdict | your code | per-question *if you keep `p` raw* | threshold / band applied per field |

The model side is **inherently per-question**: every question carries its own
`instructions`/`criteria`, so the model calibrates each one independently.
Sharpen one question's boundary by tightening *that question's* criteria — it
does not touch the others. This is the "boundary decided by the model, per
question" part, and it needs no code: it is pure config.

### Why `jev.decide(..., bool_threshold=)` is NOT per-question

`bool_threshold` is a **single value applied to every bool/noul field in the
call**. Resolution is `decide` arg > `JEV_BOOL_THRESHOLD` env > `0.5`, but it is
always one number for the whole model. So it cannot express "0.8 for
`is_urgent`, 0.3 for `is_safety_issue`" in one call.

To get **per-question numeric cuts**, do not let jev coerce the noul to a bool.
Keep the probability and cut it yourself, per field. Two documented ways:

1. **Raw probabilities, cut per question (most flexible).** Call the engine for
   the raw answer and read each `probability`, then apply that question's own
   threshold. (`jev` returns coerced models; the raw per-question probabilities
   come from `typesafe_sdk`'s `client.system_one(...)` or, on Databricks, the
   `ai_decide` VARIANT.) One call, N questions, N independent cuts.

2. **One `jev.decide` per routing decision.** If you genuinely want jev's typed
   model per question, call `jev.decide(state, OneQuestionModel,
   bool_threshold=that_question_cut)` once per question. The global threshold is
   now effectively per-question because each call has one question. Costs N
   calls instead of 1 — fine for low volume or when a question needs its own
   model/handler, wasteful at scale (prefer #1's single batched call).

### Where jev.decide IS the flexible unit

`jev.decide(state, Model, *, model=…, bool_threshold=…)` is flexible because
**per call** you can swap the return `Model` (which questions), the engine
`model`, and the global cut — all chosen at runtime from realtime data. So the
natural pattern is: a **router decides, per incoming item, which `Model` +
threshold to use**, then issues the matching `jev.decide`. The realtime data
selects the *decision*, not a per-question knob inside one decision.

### Realtime routing pattern (conceptual, no code change)

```
incoming item (realtime)
     │
     ▼
 pre-parser  ──reads tier/SLA/channel/time──▶ chooses, PER QUESTION:
     │                                         - which questions to ask
     │                                         - each question's instructions/criteria (sharpness)
     │                                         - each question's cut (threshold) or band
     ▼
 engine call  ──▶ returns raw p per question
     │
     ▼
 per-question cut:  p_q >= threshold_q ? ──▶ verdict_q ──▶ route_q(handler)
```

- **Sharpness per question** → set in that question's `instructions`/`criteria` (model side, config).
- **Cut per question** → applied in code on the raw `p`, using a threshold the pre-parser chose from realtime signals.
- **Routing** → branch on each question's verdict to its own jev follow-up / handler.

### Recommended split for this use case

- Keep questions' `instructions`/`criteria` **tight and per-question** — this is the model-decided boundary, and it is already per-question for free.
- Return **raw probabilities** (don't bake a global `bool_threshold`), so each question keeps its full `p`.
- Apply **per-question thresholds/bands in code**, chosen per item from realtime data.
- Use `jev.decide` as the **per-item decision unit** when realtime data should pick the whole question set + model; use the raw single-call path when you want all per-question cuts from one call.

`jev.decide` is the flexible *entry point* (swap model/threshold/question-set
per call); it is **not** the place for per-question thresholds inside a single
multi-question call — those stay in your coercion on the raw `p`.
```
