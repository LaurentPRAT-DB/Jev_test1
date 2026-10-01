"""Consume a batch, query the model ONCE (content-only), route per SLA.

    python run.py                 # offline stub (no API, no credit)
    python run.py --engine jev    # live TypeSafe jev (1 batched credit call)
    python run.py --engine ai_decide   # live Databricks ai_decide (1 batched call)

Flow: pull batch -> one engine call for all bodies -> raw p per ticket (SLA-blind)
-> apply each ticket's SLA cut -> verdict + route.
"""

from __future__ import annotations

import argparse
import os
import sys

# allow `python run.py` from the folder or the repo root
sys.path.insert(0, os.path.dirname(__file__))

from engine import get_probs
from tickets import pull_batch
from router import load_config, route


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["stub", "jev", "ai_decide"], default="stub")
    args = ap.parse_args()

    if args.engine == "jev":
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

    cfg = load_config()
    batch = pull_batch()
    bodies = [t.body for t in batch]

    probs = get_probs(bodies, cfg, backend=args.engine)  # ONE call for the batch

    print(f"engine={args.engine}  (content-only p, then per-SLA cut)\n")
    print(f"{'id':4} {'sla':11} {'p':>5}  {'cut(crit/rev)':14} {'verdict':9} route")
    print("-" * 70)
    for t, p in zip(batch, probs, strict=True):
        verdict, action = route(t.sla, p, cfg)
        cuts = cfg["sla_cuts"][t.sla]
        cutstr = f"{cuts['critical']:.2f}/{cuts['review']:.2f}"
        print(f"{t.id:4} {t.sla:11} {p:5.2f}  {cutstr:14} {verdict:9} {action}")

    # highlight the identical-content pair
    same = [t for t in batch if t.body == batch[0].body]
    if len(same) > 1:
        print("\nidentical content, different SLA ->")
        for t in same:
            p = probs[batch.index(t)]
            v, a = route(t.sla, p, cfg)
            print(f"  {t.id} {t.sla:11} p={p:.2f} -> {v} ({a})")


if __name__ == "__main__":
    main()
