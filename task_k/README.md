# Task K — Regulatory Submission Bundle Validator

Validates an eCTD-style submission bundle against a JSON spec. Returns a structured defect report; never raises on malformed input.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from pathlib import Path
from bundle_validator import validate_bundle, BundleSpec

spec = BundleSpec.model_validate_json(Path("fixtures/bundle_spec.json").read_text())
report = validate_bundle(Path("my_bundle"), spec)
print(report.verdict)           # CONFORMANT or NON_CONFORMANT
for d in report.defects:
    print(d.severity, d.defect_class, d.file_path, d.message)
```

## Run Tests

```bash
pytest -v
```

## Generate Example Bundle

```bash
python fixtures/generate_conformant.py
```

---

## Defect Classes

| Class | Severity | Planted Example |
|---|---|---|
| `MISSING_REQUIRED_FOLDER` | BLOCKING | Delete `m3/` from bundle |
| `UNEXPECTED_FOLDER` | MINOR | Add `m6/` at bundle root |
| `MISPLACED_FILE` | MAJOR | Drop `report.txt` directly under `m3/` instead of `m3/quality/` |
| `NAMING_VIOLATION` | MINOR | Add `m3/quality/report.docx` (`.docx` not in allowed patterns) |
| `CHECKSUM_MISMATCH` | BLOCKING | Edit `m1/regional/cover-letter.txt` after manifest was written |
| `MISSING_MANIFEST_ENTRY` | MAJOR | Add a new file without adding its hash to `manifest.md5` |
| `ORPHAN_FILE` | MINOR | Add `m5/clinical/ghost.txt` to manifest but not to disk |
| `MANIFEST_MALFORMED` | BLOCKING | Write binary/non-UTF-8 content to `manifest.md5`, or set an invalid `checksum_algorithm` in the spec |
| `BACKBONE_MALFORMED` | BLOCKING | Write `<ectd><unclosed>` to `backbone.xml`, or replace `backbone.xml` with a directory |
| `BACKBONE_MISSING_REFERENCE` | MAJOR | Add `<leaf/>` with no `href` attribute to backbone |
| `DISK_MISSING_BACKBONE_REF` | BLOCKING | Delete `m2/summaries/overview.txt` while backbone still references it |
| `BACKBONE_UNREFERENCED_FILE` | MINOR | Add a file on disk without adding a `<leaf>` entry in backbone |
