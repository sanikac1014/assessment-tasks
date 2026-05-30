#!/usr/bin/env python3
"""Run this once to produce the conformant example bundle under fixtures/conformant/."""
import hashlib
from pathlib import Path

BUNDLE_FILES = {
    "m1/regional/cover-letter.txt": b"Cover letter content.",
    "m2/summaries/overview.txt": b"CTD overview summary.",
    "m3/quality/cmc-report.txt": b"CMC manufacturing quality report.",
    "m4/nonclinical/tox-study.txt": b"Nonclinical toxicology study.",
    "m5/clinical/study-001.txt": b"Clinical study report 001.",
}

BACKBONE = """\
<?xml version="1.0" encoding="UTF-8"?>
<ectd version="3.2.2">
  <m1><leaf href="m1/regional/cover-letter.txt"/></m1>
  <m2><leaf href="m2/summaries/overview.txt"/></m2>
  <m3><leaf href="m3/quality/cmc-report.txt"/></m3>
  <m4><leaf href="m4/nonclinical/tox-study.txt"/></m4>
  <m5><leaf href="m5/clinical/study-001.txt"/></m5>
</ectd>"""


def generate(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines = []
    for rel, content in BUNDLE_FILES.items():
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        digest = hashlib.md5(content).hexdigest()
        manifest_lines.append(f"{digest}  {rel}")

    (out_dir / "manifest.md5").write_text("\n".join(manifest_lines) + "\n")
    (out_dir / "backbone.xml").write_text(BACKBONE)
    print(f"Conformant bundle written to: {out_dir}")


if __name__ == "__main__":
    generate(Path(__file__).parent / "conformant")
