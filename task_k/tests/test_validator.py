import hashlib
import shutil
from pathlib import Path

import pytest

from bundle_validator import (
    validate_bundle,
    validate_backbone,
    checksum_manifest,
    DefectClass,
    Severity,
    Verdict,
    ValidationReport,
)
from tests.conftest import build_conformant, BUNDLE_FILES, BACKBONE_XML


# ── helpers ──────────────────────────────────────────────────────────────────

def classes(report):
    return {d.defect_class for d in report.defects}


# ── conformant baseline ───────────────────────────────────────────────────────

def test_conformant_passes(bundle, spec):
    r = validate_bundle(bundle, spec)
    assert r.verdict == Verdict.CONFORMANT
    assert r.defects == []


def test_conformant_leaf_count(bundle, spec):
    r = validate_bundle(bundle, spec)
    assert r.total_leaf_count == len(BUNDLE_FILES)


def test_conformant_per_module_all_zero(bundle, spec):
    r = validate_bundle(bundle, spec)
    assert all(v == 0 for v in r.per_module_defects.values())


def test_checksum_manifest_clean_on_conformant(bundle, spec):
    cs = checksum_manifest(bundle, spec)
    assert cs.mismatches == 0
    assert cs.missing == 0
    assert cs.orphans == 0


def test_backbone_clean_on_conformant(bundle, spec):
    bb = validate_backbone(bundle / "backbone.xml", spec)
    assert bb.well_formed
    assert bb.defects == []


# ── missing module folders ────────────────────────────────────────────────────

@pytest.mark.parametrize("module", ["m1", "m2", "m3", "m4", "m5"])
def test_missing_module_folder(tmp_path, spec, module):
    root = build_conformant(tmp_path / "bundle")
    shutil.rmtree(root / module)
    r = validate_bundle(root, spec)
    assert r.verdict == Verdict.NON_CONFORMANT
    assert DefectClass.MISSING_REQUIRED_FOLDER in classes(r)


# ── folder / file placement defects ──────────────────────────────────────────

def test_unexpected_top_level_folder(bundle, spec):
    (bundle / "m6").mkdir()
    r = validate_bundle(bundle, spec)
    assert DefectClass.UNEXPECTED_FOLDER in classes(r)


def test_missing_required_subfolder(bundle, spec):
    shutil.rmtree(bundle / "m3" / "quality")
    r = validate_bundle(bundle, spec)
    found = [d for d in r.defects if d.defect_class == DefectClass.MISSING_REQUIRED_FOLDER and "quality" in (d.file_path or "")]
    assert found


def test_misplaced_file(bundle, spec):
    (bundle / "m3" / "stray.txt").write_bytes(b"stray")
    r = validate_bundle(bundle, spec)
    assert DefectClass.MISPLACED_FILE in classes(r)


# ── naming violation ──────────────────────────────────────────────────────────

def test_naming_violation(bundle, spec):
    bad = bundle / "m3" / "quality" / "report.docx"
    bad.write_bytes(b"word doc")
    # add it to manifest and backbone so only naming defect fires
    digest = hashlib.md5(b"word doc").hexdigest()
    existing = (bundle / "manifest.md5").read_text()
    (bundle / "manifest.md5").write_text(existing + f"{digest}  m3/quality/report.docx\n")
    r = validate_bundle(bundle, spec)
    assert DefectClass.NAMING_VIOLATION in classes(r)


# ── checksum defects ──────────────────────────────────────────────────────────

def test_checksum_mismatch(bundle, spec):
    (bundle / "m1" / "regional" / "cover-letter.txt").write_bytes(b"tampered content")
    r = validate_bundle(bundle, spec)
    assert DefectClass.CHECKSUM_MISMATCH in classes(r)


def test_missing_manifest_entry(bundle, spec):
    extra = bundle / "m5" / "clinical" / "extra.txt"
    extra.write_bytes(b"extra file")
    r = validate_bundle(bundle, spec)
    assert DefectClass.MISSING_MANIFEST_ENTRY in classes(r)


def test_orphan_in_manifest(bundle, spec):
    existing = (bundle / "manifest.md5").read_text()
    (bundle / "manifest.md5").write_text(existing + "deadbeef00000000  m5/clinical/ghost.txt\n")
    r = validate_bundle(bundle, spec)
    assert DefectClass.ORPHAN_FILE in classes(r)


# ── backbone defects ──────────────────────────────────────────────────────────

def test_backbone_malformed_xml(bundle, spec):
    (bundle / "backbone.xml").write_text("<ectd><unclosed>")
    r = validate_bundle(bundle, spec)
    assert DefectClass.BACKBONE_MALFORMED in classes(r)


def test_backbone_not_found(bundle, spec):
    (bundle / "backbone.xml").unlink()
    r = validate_bundle(bundle, spec)
    assert DefectClass.BACKBONE_MALFORMED in classes(r)


def test_backbone_missing_href(bundle, spec):
    bad_bb = """\
<?xml version="1.0" encoding="UTF-8"?>
<ectd version="3.2.2">
  <m1><leaf href="m1/regional/cover-letter.txt"/></m1>
  <m2><leaf href="m2/summaries/overview.txt"/></m2>
  <m3><leaf/></m3>
  <m4><leaf href="m4/nonclinical/tox-study.txt"/></m4>
  <m5><leaf href="m5/clinical/study-001.txt"/></m5>
</ectd>"""
    (bundle / "backbone.xml").write_text(bad_bb)
    r = validate_bundle(bundle, spec)
    assert DefectClass.BACKBONE_MISSING_REFERENCE in classes(r)


def test_backbone_references_missing_file(bundle, spec):
    (bundle / "m2" / "summaries" / "overview.txt").unlink()
    r = validate_bundle(bundle, spec)
    assert DefectClass.DISK_MISSING_BACKBONE_REF in classes(r)


def test_backbone_unreferenced_file(bundle, spec):
    extra = bundle / "m4" / "nonclinical" / "extra.txt"
    extra.write_bytes(b"extra nonclinical")
    digest = hashlib.md5(b"extra nonclinical").hexdigest()
    existing = (bundle / "manifest.md5").read_text()
    (bundle / "manifest.md5").write_text(existing + f"{digest}  m4/nonclinical/extra.txt\n")
    r = validate_bundle(bundle, spec)
    assert DefectClass.BACKBONE_UNREFERENCED_FILE in classes(r)


# ── bidirectional backbone reconciliation ────────────────────────────────────

def test_bidirectional_forward_and_reverse(tmp_path, spec):
    root = build_conformant(tmp_path / "bundle")

    # add a disk file not in backbone
    ghost = root / "m5" / "clinical" / "unreferenced.txt"
    ghost.write_bytes(b"not in backbone")
    d = hashlib.md5(b"not in backbone").hexdigest()
    existing = (root / "manifest.md5").read_text()
    (root / "manifest.md5").write_text(existing + f"{d}  m5/clinical/unreferenced.txt\n")

    bb = validate_backbone(root / "backbone.xml", spec)
    bb_classes = {d.defect_class for d in bb.defects}
    assert DefectClass.BACKBONE_UNREFERENCED_FILE in bb_classes
    assert DefectClass.DISK_MISSING_BACKBONE_REF not in bb_classes

    # now remove a referenced file
    (root / "m1" / "regional" / "cover-letter.txt").unlink()
    bb2 = validate_backbone(root / "backbone.xml", spec)
    bb2_classes = {d.defect_class for d in bb2.defects}
    assert DefectClass.DISK_MISSING_BACKBONE_REF in bb2_classes


# ── graceful handling ─────────────────────────────────────────────────────────

def test_corrupt_xml_no_crash(tmp_path, spec):
    root = build_conformant(tmp_path / "bundle")
    (root / "backbone.xml").write_bytes(b"\xff\xfe<broken xml \x00\x01")
    r = validate_bundle(root, spec)
    assert r.verdict == Verdict.NON_CONFORMANT
    assert DefectClass.BACKBONE_MALFORMED in classes(r)


def test_nonexistent_bundle_no_crash(tmp_path, spec):
    r = validate_bundle(tmp_path / "does_not_exist", spec)
    assert r.verdict == Verdict.NON_CONFORMANT


def test_empty_bundle_no_crash(tmp_path, spec):
    root = tmp_path / "empty"
    root.mkdir()
    r = validate_bundle(root, spec)
    assert r.verdict == Verdict.NON_CONFORMANT


# ── verdict and severity ──────────────────────────────────────────────────────

def test_verdict_non_conformant_when_defects_exist(bundle, spec):
    shutil.rmtree(bundle / "m1")
    r = validate_bundle(bundle, spec)
    assert r.verdict == Verdict.NON_CONFORMANT


def test_blocking_severity_on_missing_module(bundle, spec):
    shutil.rmtree(bundle / "m2")
    r = validate_bundle(bundle, spec)
    blocking = [d for d in r.defects if d.severity == Severity.BLOCKING]
    assert blocking


def test_per_module_defect_count_increments(bundle, spec):
    shutil.rmtree(bundle / "m3" / "quality")
    r = validate_bundle(bundle, spec)
    assert r.per_module_defects["m3"] > 0
    assert r.per_module_defects["m1"] == 0


# ── crash-proof malformed inputs ──────────────────────────────────────────────

def test_binary_manifest_returns_report_not_exception(tmp_path, spec):
    root = build_conformant(tmp_path / "bundle")
    (root / "manifest.md5").write_bytes(b"\xff\xfe binary \x00 garbage \xab\xcd")
    r = validate_bundle(root, spec)
    assert isinstance(r, ValidationReport)
    assert r.verdict == Verdict.NON_CONFORMANT
    assert DefectClass.MANIFEST_MALFORMED in classes(r)


def test_invalid_checksum_algorithm_returns_report_not_exception(tmp_path, spec):
    from bundle_validator.models import BundleSpec
    root = build_conformant(tmp_path / "bundle")
    bad_data = spec.model_dump()
    bad_data["checksum_algorithm"] = "notareadigest"
    bad_spec = BundleSpec.model_validate(bad_data)
    r = validate_bundle(root, bad_spec)
    assert isinstance(r, ValidationReport)
    assert DefectClass.MANIFEST_MALFORMED in classes(r)


def test_backbone_is_directory_returns_report_not_exception(tmp_path, spec):
    root = build_conformant(tmp_path / "bundle")
    (root / "backbone.xml").unlink()
    (root / "backbone.xml").mkdir()
    r = validate_bundle(root, spec)
    assert isinstance(r, ValidationReport)
    assert r.verdict == Verdict.NON_CONFORMANT
    assert DefectClass.BACKBONE_MALFORMED in classes(r)


def test_manifest_is_directory_returns_report_not_exception(tmp_path, spec):
    root = build_conformant(tmp_path / "bundle")
    (root / "manifest.md5").unlink()
    (root / "manifest.md5").mkdir()
    r = validate_bundle(root, spec)
    assert isinstance(r, ValidationReport)
    assert r.verdict == Verdict.NON_CONFORMANT
    assert DefectClass.MANIFEST_MALFORMED in classes(r)


def test_checksum_manifest_standalone_binary_no_raise(tmp_path, spec):
    """checksum_manifest called directly must not raise on a non-UTF-8 manifest."""
    from bundle_validator import checksum_manifest, ChecksumManifest
    root = build_conformant(tmp_path / "bundle")
    (root / "manifest.md5").write_bytes(b"\xff\xfe binary \x00 garbage \xab\xcd")
    cs = checksum_manifest(root, spec)
    assert isinstance(cs, ChecksumManifest)
    assert cs.malformed is True


def test_checksum_manifest_standalone_directory_no_raise(tmp_path, spec):
    """checksum_manifest called directly must not raise when manifest is a directory."""
    from bundle_validator import checksum_manifest, ChecksumManifest
    root = build_conformant(tmp_path / "bundle")
    (root / "manifest.md5").unlink()
    (root / "manifest.md5").mkdir()
    cs = checksum_manifest(root, spec)
    assert isinstance(cs, ChecksumManifest)
    assert cs.malformed is True
