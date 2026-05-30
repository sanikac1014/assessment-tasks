import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import (
    BundleSpec,
    ValidationReport,
    BackboneReport,
    ChecksumManifest,
    Defect,
    DefectClass,
    Severity,
    Verdict,
    ChecksumEntry,
)

_SEVERITY = {
    DefectClass.MISSING_REQUIRED_FOLDER: Severity.BLOCKING,
    DefectClass.UNEXPECTED_FOLDER: Severity.MINOR,
    DefectClass.MISPLACED_FILE: Severity.MAJOR,
    DefectClass.NAMING_VIOLATION: Severity.MINOR,
    DefectClass.CHECKSUM_MISMATCH: Severity.BLOCKING,
    DefectClass.MISSING_MANIFEST_ENTRY: Severity.MAJOR,
    DefectClass.ORPHAN_FILE: Severity.MINOR,
    DefectClass.BACKBONE_MALFORMED: Severity.BLOCKING,
    DefectClass.BACKBONE_MISSING_REFERENCE: Severity.MAJOR,
    DefectClass.DISK_MISSING_BACKBONE_REF: Severity.BLOCKING,
    DefectClass.BACKBONE_UNREFERENCED_FILE: Severity.MINOR,
}


def _d(cls: DefectClass, path: str = None, msg: str = "") -> Defect:
    return Defect(defect_class=cls, severity=_SEVERITY[cls], file_path=path, message=msg)


def _hash_file(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base)).replace("\\", "/")


def checksum_manifest(bundle_root: Path, spec: BundleSpec = None) -> ChecksumManifest:
    algorithm = spec.checksum_algorithm if spec else "md5"
    manifest_name = spec.manifest_filename if spec else "manifest.md5"
    backbone_name = spec.backbone_filename if spec else "backbone.xml"

    manifest_path = bundle_root / manifest_name
    known: dict[str, str] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                known[parts[1].strip()] = parts[0].strip()

    skip = {manifest_name, backbone_name}
    leaves = [p for p in bundle_root.rglob("*") if p.is_file() and p.name not in skip]

    entries: list[ChecksumEntry] = []
    seen: set[str] = set()

    for leaf in leaves:
        rel = _rel(leaf, bundle_root)
        actual = _hash_file(leaf, algorithm)
        expected = known.get(rel)
        seen.add(rel)

        if expected is None:
            status = "MISSING_FROM_MANIFEST"
        elif actual != expected:
            status = "MISMATCH"
        else:
            status = "OK"

        entries.append(ChecksumEntry(path=rel, expected=expected, actual=actual, status=status))

    for path, digest in known.items():
        if path not in seen:
            entries.append(ChecksumEntry(path=path, expected=digest, actual=None, status="ORPHAN"))

    return ChecksumManifest(
        entries=entries,
        mismatches=sum(1 for e in entries if e.status == "MISMATCH"),
        missing=sum(1 for e in entries if e.status == "MISSING_FROM_MANIFEST"),
        orphans=sum(1 for e in entries if e.status == "ORPHAN"),
    )


def validate_backbone(xml_path: Path, spec: BundleSpec) -> BackboneReport:
    bundle_root = xml_path.parent
    defects: list[Defect] = []

    if not xml_path.exists():
        return BackboneReport(
            well_formed=False,
            defects=[_d(DefectClass.BACKBONE_MALFORMED, str(xml_path), "Backbone file not found")],
        )

    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError as exc:
        return BackboneReport(
            well_formed=False,
            defects=[_d(DefectClass.BACKBONE_MALFORMED, xml_path.name, f"XML parse error: {exc}")],
        )

    root_el = tree.getroot()
    referenced: set[str] = set()

    for el in root_el.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "leaf":
            href = (
                el.get("{http://www.w3.org/1999/xlink}href")
                or el.get("href")
            )
            if not href:
                defects.append(_d(DefectClass.BACKBONE_MISSING_REFERENCE, None, "<leaf> element has no href attribute"))
            else:
                referenced.add(href.strip())

    # forward check: every reference must exist on disk
    for ref in referenced:
        if not (bundle_root / ref).exists():
            defects.append(_d(DefectClass.DISK_MISSING_BACKBONE_REF, ref, f"Backbone references '{ref}' but file not on disk"))

    # reverse check: every content-module leaf must be referenced
    skip = {spec.manifest_filename, spec.backbone_filename}
    for module_name in spec.modules:
        module_dir = bundle_root / module_name
        if not module_dir.exists():
            continue
        for leaf in module_dir.rglob("*"):
            if leaf.is_file() and leaf.name not in skip:
                rel = _rel(leaf, bundle_root)
                if rel not in referenced:
                    defects.append(_d(DefectClass.BACKBONE_UNREFERENCED_FILE, rel, f"'{rel}' not referenced in backbone"))

    return BackboneReport(well_formed=True, defects=defects)


def validate_bundle(bundle_root: Path, spec: BundleSpec) -> ValidationReport:
    defects: list[Defect] = []
    per_module: dict[str, int] = {m: 0 for m in spec.modules}

    if not bundle_root.exists() or not bundle_root.is_dir():
        return ValidationReport(
            total_leaf_count=0,
            per_module_defects=per_module,
            defects=[_d(DefectClass.MISSING_REQUIRED_FOLDER, str(bundle_root), "Bundle root does not exist")],
            verdict=Verdict.NON_CONFORMANT,
        )

    def add(defect: Defect, module: str = None):
        defects.append(defect)
        if module and module in per_module:
            per_module[module] += 1

    # top-level folder checks
    top_dirs = {p.name for p in bundle_root.iterdir() if p.is_dir()}
    non_module_files = {spec.manifest_filename, spec.backbone_filename}

    for module_name in spec.modules:
        if module_name not in top_dirs:
            add(_d(DefectClass.MISSING_REQUIRED_FOLDER, module_name, f"Required module folder '{module_name}' is missing"), module_name)

    for item in bundle_root.iterdir():
        if item.is_dir() and item.name not in spec.modules:
            add(_d(DefectClass.UNEXPECTED_FOLDER, item.name, f"Unexpected top-level folder '{item.name}'"))

    # per-module checks
    for module_name, module_spec in spec.modules.items():
        module_dir = bundle_root / module_name
        if not module_dir.exists():
            continue

        # required subfolders
        existing_subs = {p.name for p in module_dir.iterdir() if p.is_dir()}
        for sub in module_spec.required_subfolders:
            if sub not in existing_subs:
                add(
                    _d(DefectClass.MISSING_REQUIRED_FOLDER, f"{module_name}/{sub}", f"Required subfolder '{sub}' missing in {module_name}"),
                    module_name,
                )

        # misplaced files (directly under module root when subfolders are defined)
        has_subs = bool(module_spec.required_subfolders or module_spec.optional_subfolders)
        if has_subs:
            for item in module_dir.iterdir():
                if item.is_file() and item.name not in non_module_files:
                    rel = _rel(item, bundle_root)
                    add(_d(DefectClass.MISPLACED_FILE, rel, f"File '{item.name}' placed directly under '{module_name}'; expected inside a subfolder"), module_name)

        # naming conventions
        if module_spec.file_patterns:
            patterns = [re.compile(p) for p in module_spec.file_patterns]
            for leaf in module_dir.rglob("*"):
                if leaf.is_file() and leaf.name not in non_module_files:
                    if not any(pat.search(leaf.name) for pat in patterns):
                        rel = _rel(leaf, bundle_root)
                        add(
                            _d(DefectClass.NAMING_VIOLATION, rel, f"'{leaf.name}' does not match patterns for {module_name}: {module_spec.file_patterns}"),
                            module_name,
                        )

    # checksum validation
    cs = checksum_manifest(bundle_root, spec)
    for entry in cs.entries:
        module = entry.path.split("/")[0]
        if entry.status == "MISMATCH":
            add(_d(DefectClass.CHECKSUM_MISMATCH, entry.path, f"Checksum mismatch: '{entry.path}'"), module)
        elif entry.status == "MISSING_FROM_MANIFEST":
            add(_d(DefectClass.MISSING_MANIFEST_ENTRY, entry.path, f"No manifest entry for '{entry.path}'"), module)
        elif entry.status == "ORPHAN":
            add(_d(DefectClass.ORPHAN_FILE, entry.path, f"Manifest references '{entry.path}' but file not found"), module)

    # backbone validation
    backbone_path = bundle_root / spec.backbone_filename
    bb = validate_backbone(backbone_path, spec)
    for defect in bb.defects:
        module = defect.file_path.split("/")[0] if defect.file_path and "/" in defect.file_path else None
        add(defect, module)

    skip = {spec.manifest_filename, spec.backbone_filename}
    total_leaves = sum(1 for p in bundle_root.rglob("*") if p.is_file() and p.name not in skip)

    return ValidationReport(
        total_leaf_count=total_leaves,
        per_module_defects=per_module,
        defects=defects,
        verdict=Verdict.CONFORMANT if not defects else Verdict.NON_CONFORMANT,
    )
