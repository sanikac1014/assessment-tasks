from enum import Enum
from typing import Optional
from pydantic import BaseModel


class DefectClass(str, Enum):
    MISSING_REQUIRED_FOLDER = "MISSING_REQUIRED_FOLDER"
    UNEXPECTED_FOLDER = "UNEXPECTED_FOLDER"
    MISPLACED_FILE = "MISPLACED_FILE"
    NAMING_VIOLATION = "NAMING_VIOLATION"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    MISSING_MANIFEST_ENTRY = "MISSING_MANIFEST_ENTRY"
    ORPHAN_FILE = "ORPHAN_FILE"
    MANIFEST_MALFORMED = "MANIFEST_MALFORMED"
    BACKBONE_MALFORMED = "BACKBONE_MALFORMED"
    BACKBONE_MISSING_REFERENCE = "BACKBONE_MISSING_REFERENCE"
    DISK_MISSING_BACKBONE_REF = "DISK_MISSING_BACKBONE_REF"
    BACKBONE_UNREFERENCED_FILE = "BACKBONE_UNREFERENCED_FILE"


class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class Verdict(str, Enum):
    CONFORMANT = "CONFORMANT"
    NON_CONFORMANT = "NON_CONFORMANT"


class Defect(BaseModel):
    defect_class: DefectClass
    severity: Severity
    file_path: Optional[str] = None
    message: str


class ValidationReport(BaseModel):
    total_leaf_count: int
    per_module_defects: dict[str, int]
    defects: list[Defect]
    verdict: Verdict


class BackboneReport(BaseModel):
    well_formed: bool
    defects: list[Defect]


class ChecksumEntry(BaseModel):
    path: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    status: str  # OK | MISMATCH | MISSING_FROM_MANIFEST | ORPHAN


class ChecksumManifest(BaseModel):
    entries: list[ChecksumEntry]
    mismatches: int
    missing: int
    orphans: int
    malformed: bool = False
    malformed_reason: str = ""


class ModuleSpec(BaseModel):
    description: str = ""
    required_subfolders: list[str] = []
    optional_subfolders: list[str] = []
    file_patterns: list[str] = []


class BundleSpec(BaseModel):
    modules: dict[str, ModuleSpec]
    checksum_algorithm: str = "md5"
    manifest_filename: str = "manifest.md5"
    backbone_filename: str = "backbone.xml"
