# Assessment Tasks K–O

Submitted by Sanika Choudhary — May 2026

Five self-contained Python packages, each with a pytest suite, README, and supporting deliverables.

---

| Task | Description | Tests |
|---|---|---|
| [task_k](./task_k) | Regulatory Submission Bundle Validator — validates an eCTD-style folder structure, checksums, and XML backbone | 29 |
| [task_l](./task_l) | Evidence-Grade Scoring Engine — scores a body of scientific evidence from SPECULATIVE to CONSENSUS using a YAML-configurable rubric; monotonicity proven via property tests | 20 |
| [task_m](./task_m) | Counterfactual Treatment-Effect Comparator — estimates ATE with IPTW and G-computation, demonstrates bias correction under confounding against known-truth | 20 |
| [task_n](./task_n) | Rate-Limited Multi-Source Ingestion Queue — token-bucket rate limiting, idempotent dedup, backpressure, and dead-letter handling | 21 |
| [task_o](./task_o) | Schema-Migration and Provenance Diff Tool — diffs two table schemas, classifies changes as breaking/non-breaking, emits reversible SQL migration and provenance record | 22 |

**Total: 112 tests across all tasks**

---

## Running a task

```bash
cd task_k          # or task_l, task_m, task_n, task_o
pip install -e ".[dev]"
pytest -v
```

## Requirements

Python 3.11+. Each task declares its own dependencies in `pyproject.toml`.