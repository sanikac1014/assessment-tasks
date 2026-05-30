import hashlib
from pathlib import Path
import pytest
from bundle_validator.models import BundleSpec

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

BUNDLE_FILES = {
    "m1/regional/cover-letter.txt": b"Cover letter content.",
    "m2/summaries/overview.txt": b"CTD overview summary.",
    "m3/quality/cmc-report.txt": b"CMC manufacturing quality report.",
    "m4/nonclinical/tox-study.txt": b"Nonclinical toxicology study.",
    "m5/clinical/study-001.txt": b"Clinical study report 001.",
}

BACKBONE_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<ectd version="3.2.2">
  <m1><leaf href="m1/regional/cover-letter.txt"/></m1>
  <m2><leaf href="m2/summaries/overview.txt"/></m2>
  <m3><leaf href="m3/quality/cmc-report.txt"/></m3>
  <m4><leaf href="m4/nonclinical/tox-study.txt"/></m4>
  <m5><leaf href="m5/clinical/study-001.txt"/></m5>
</ectd>"""


def build_conformant(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    for rel, content in BUNDLE_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        digest = hashlib.md5(content).hexdigest()
        manifest_lines.append(f"{digest}  {rel}")
    (root / "manifest.md5").write_text("\n".join(manifest_lines) + "\n")
    (root / "backbone.xml").write_text(BACKBONE_XML)
    return root


@pytest.fixture
def spec():
    return BundleSpec.model_validate_json((FIXTURES_DIR / "bundle_spec.json").read_text())


@pytest.fixture
def bundle(tmp_path, spec):
    return build_conformant(tmp_path / "bundle")
