"""Measure ai_decide throughput vs batch size to find the jev crossover.

Runs ai_decide (1 noul) over N rows in a single batched SQL call, for several N.
CLI/warehouse fixed cost is constant across runs, so the SLOPE between points is
the clean per-row marginal cost (what a Spark job pays). Fits fixed + marginal,
then solves the crossover against jev's measured per-item rate.

DBU only — makes NO jev calls.
"""

from __future__ import annotations

import sys
import time

sys.path.insert(0, ".")
from engine import probs_ai_decide
from router import load_config

cfg = load_config()
BASE = ("Your API intermittently returns HTTP 500 on POST /v2/events; "
        "about 1 in 5 requests fails and the retry queue is backing up")

Ns = [1, 20, 60, 150]
pts: list[tuple[int, float]] = []
for n in Ns:
    bodies = [f"{BASE}. [row {i}]" for i in range(n)]  # vary to defeat caching
    t0 = time.perf_counter()
    probs = probs_ai_decide(bodies, cfg)
    dt = time.perf_counter() - t0
    assert len(probs) == n
    pts.append((n, dt))
    print(f"N={n:4}  total={dt:7.2f}s  per-row={dt/n:6.3f}s", flush=True)

# linear fit total = fixed + marginal * N  (least squares)
import statistics
xs = [n for n, _ in pts]
ys = [t for _, t in pts]
xbar, ybar = statistics.mean(xs), statistics.mean(ys)
sxx = sum((x - xbar) ** 2 for x in xs)
sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
marginal = sxy / sxx
fixed = ybar - marginal * xbar
print(f"\nai_decide fit:  total ≈ {fixed:.2f}s fixed + {marginal:.4f}s/row  "
      f"(throughput ≈ {1/marginal:.1f} rows/s marginal)")
print(f"  NOTE: 'fixed' here includes CLI (~5-10s) that a real Spark/SQL job over "
      f"a Delta table does NOT pay — treat it as an upper bound on overhead.")

# jev model: measured ~0.09 s/item batched (.map), ~0.2s fixed per call,
# but one map call is payload-bounded, so at high N jev needs CHUNKS of ~C items.
JEV_PER_ITEM = 0.09
JEV_FIXED = 0.2
JEV_CHUNK = 100  # assumed max items per map call (adjust to real limit)

def jev_time(n: int) -> float:
    import math
    calls = math.ceil(n / JEV_CHUNK)
    return calls * JEV_FIXED + n * JEV_PER_ITEM

def ai_time(n: int) -> float:
    return fixed + marginal * n

print("\nmodeled wall-clock (lower = faster):")
print(f"{'N':>7} {'ai_decide':>12} {'jev':>10}  winner")
cross = None
for n in [1, 10, 50, 100, 500, 1000, 5000, 20000, 100000]:
    a, j = ai_time(n), jev_time(n)
    win = "ai_decide" if a < j else "jev"
    if cross is None and a < j:
        cross = n
    print(f"{n:>7} {a:>11.1f}s {j:>9.1f}s  {win}")

if cross:
    print(f"\n≈ crossover near N≈{cross}: above it the ai_decide batch job finishes "
          f"first; below it jev's low per-call latency wins.")
else:
    print("\nno crossover in range — jev stays faster across all tested N "
          "(ai_decide marginal slower than jev per-item at this scale).")
