# Assessment Tasks K–O

Submitted by Sanika Choudhary — May 2026

Five self-contained Python packages, each with a pytest suite, README, and supporting deliverables.

---

| Task | Description | Tests |
|---|---|---|
| [task_k](./task_k) | Regulatory Submission Bundle Validator — validates an eCTD-style folder structure, checksums, and XML backbone; crash-proof on malformed inputs | 32 |
| [task_l](./task_l) | Evidence-Grade Scoring Engine — scores a body of scientific evidence from SPECULATIVE to CONSENSUS using a YAML-configurable rubric; monotonicity proven via property tests; contribution breakdown reconciles with clamped score | 21 |
| [task_m](./task_m) | Counterfactual Treatment-Effect Comparator — estimates ATE with IPTW and G-computation, demonstrates bias correction under confounding against known-truth; coverage ≥90% at n=2000; positivity violation surfaced in recovery path | 21 |
| [task_n](./task_n) | Rate-Limited Multi-Source Ingestion Queue — token-bucket rate limiting, idempotent dedup with bounded FIFO eviction, backpressure, and dead-letter handling; stress harness proves all four properties | 22 |
| [task_o](./task_o) | Schema-Migration and Provenance Diff Tool — diffs two table schemas, classifies changes as breaking/non-breaking, emits reversible SQL migration and provenance record; content-based provenance hashes; SQLite round-trip validation | 25 |

**Total: 121 tests across all tasks**

---

## Running a task

```bash
cd task_k          # or task_l, task_m, task_n, task_o
pip install -e ".[dev]"
pytest -v
```

## Requirements

Python 3.11+. Each task declares its own dependencies in `pyproject.toml`.