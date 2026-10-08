"""Catalog and project domain. Refreshes never modify images or annotations."""

from datetime import datetime
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import inspect, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.oncometra_models import (
    WorkspaceProject, WorkspaceUser, CatalogDataset, ProjectDataset, CohortItem,
    CaseSourceLink,
)


def project_payload(row):
    return {key: getattr(row, key) for key in (
        "id", "name", "cancer_origin", "modality", "target", "guidelines",
        "lesion_sites", "color", "version",
    )}


def visible_projects(db, user):
    query = select(WorkspaceProject).order_by(WorkspaceProject.created_at, WorkspaceProject.name)
    if user.role != "admin":
        query = query.where(WorkspaceProject.id.in_(user.projects))
    return list(db.scalars(query))


def seed_projects(db, defaults):
    # An additive backfill only. Edited guidelines and existing access survive restarts.
    for item in defaults:
        if not db.get(WorkspaceProject, item["id"]):
            db.add(WorkspaceProject(id=item["id"], name=item["name"],
                cancer_origin=item["name"], modality=item["modality"], target=item["target"],
                color=item["color"], guidelines="Define inclusion criteria and annotation instructions before assigning a study."))
    db.flush()


def safe_url(value, *, empty=False):
    if not value and empty:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use an HTTPS URL without embedded credentials")
    return value


def dataset_payload(row):
    result = {key: getattr(row, key) for key in (
        "id", "registry", "external_id", "name", "url", "tumor_types", "modalities",
        "access", "license_name", "license_url", "commercial_use", "longitudinal",
        "segmentations", "status", "notes", "evidence", "version",
        "dicom_ready", "dicom_path", "indexed_patients", "tumor_detail",
        "totalseg_status", "totalseg_detail", "totalseg_error",
    )}
    result["last_seen_at"] = row.last_seen_at.isoformat()
    result["dicom_ready"] = bool(result["dicom_ready"])
    result["profile"] = (row.source_snapshot or {}).get("profile") or {}
    return result


def upsert_discovery(db, record):
    row = db.scalar(select(CatalogDataset).where(CatalogDataset.registry == record["registry"],
                    CatalogDataset.external_id == record["external_id"]))
    created = row is None
    if created:
        fields = {key: value for key, value in record.items() if key in {
            "registry", "external_id", "name", "url", "tumor_types", "modalities",
            "access", "license_name", "license_url", "commercial_use", "longitudinal",
            "segmentations", "notes", "evidence",
        }}
        # Conflict handling is atomic without a SQLite savepoint committing early.
        result = db.execute(sqlite_insert(CatalogDataset).values(id=str(uuid4()), **fields)
            .on_conflict_do_nothing(index_elements=["registry", "external_id"]))
        created = result.rowcount == 1
        row = db.scalar(select(CatalogDataset).where(CatalogDataset.registry == record["registry"],
                        CatalogDataset.external_id == record["external_id"]))
    # Source refresh and human curation are deliberately separate.
    row.source_snapshot = record
    row.last_seen_at = datetime.utcnow()
    db.flush()
    return row, created


def ensure_imaging_index_schema(engine):
    """Add imaging-index columns when the local database was created before them."""
    inspector = inspect(engine)
    if "catalog_datasets" not in inspector.get_table_names():
        return
    present = {column["name"] for column in inspector.get_columns("catalog_datasets")}
    statements = []
    if "dicom_ready" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN dicom_ready BOOLEAN NOT NULL DEFAULT 0")
    if "dicom_path" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN dicom_path TEXT NOT NULL DEFAULT ''")
    if "indexed_patients" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN indexed_patients INTEGER NOT NULL DEFAULT 0")
    if "tumor_detail" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN tumor_detail TEXT NOT NULL DEFAULT ''")
    if "totalseg_status" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN totalseg_status VARCHAR(16) NOT NULL DEFAULT ''")
    if "totalseg_error" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN totalseg_error TEXT NOT NULL DEFAULT ''")
    if "totalseg_detail" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN totalseg_detail TEXT NOT NULL DEFAULT ''")
    if "totalseg_at" not in present:
        statements.append("ALTER TABLE catalog_datasets ADD COLUMN totalseg_at DATETIME")
    if "catalog_patient_index" in inspector.get_table_names():
        patient_columns = {column["name"] for column in inspector.get_columns("catalog_patient_index")}
        if "totalseg" not in patient_columns:
            statements.append("ALTER TABLE catalog_patient_index ADD COLUMN totalseg JSON NOT NULL DEFAULT '[]'")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


# Already shown in the curated dataset fields. The patient list is never copied.
_PROFILE_SKIP = {
    "id", "external_id", "registry", "name", "url", "tumor", "tumor_types",
    "dl_path", "license_name", "license_url", "commercial_use", "evidence",
    "patients_indexed_at", "patients_index_error",
}


def dataset_profile(raw):
    """Dataset fields that do not already have a curated column, excluding patients."""
    profile = {}
    for key, value in raw.items():
        if key in _PROFILE_SKIP:
            continue
        if key == "patients":
            if isinstance(value, (list, dict)) or value in (None, ""):
                continue
            profile["patient_count"] = value
            continue
        if value in (None, "", [], {}):
            continue
        profile[key] = value
    return profile


def apply_imaging_index(db, dataset, raw):
    """Copy the WP05 dataset record and DICOM folder. The patient index stays behind."""
    if "tumor" in raw:
        detail = raw.get("tumor") or ""
        if isinstance(detail, list):
            detail = "\n".join(str(item) for item in detail)
        dataset.tumor_detail = " ".join(str(detail).split())[:4000]
    if "dl_on" in raw or "dl_path" in raw:
        path = str(raw.get("dl_path") or "").strip()
        if len(path) > 512:
            raise ValueError(f"DICOM path for {dataset.external_id} exceeds 512 characters")
        dataset.dicom_ready = bool(raw.get("dl_on")) and bool(path)
        dataset.dicom_path = path
    profile = dataset_profile(raw)
    if profile:
        snapshot = dict(dataset.source_snapshot or {})
        snapshot["profile"] = profile
        dataset.source_snapshot = snapshot
    return 0


def validate_cohort_identity(existing, record):
    for key in ("patient_id", "study_uid", "series_uid", "modality"):
        if getattr(existing, key) != record[key]:
            raise HTTPException(409, f"Source identity changed for {existing.external_id}: {key}. Use a new external_id; existing annotations were not modified.")


def prepare_import_link(db, project_id, cohort_item_id):
    item = db.get(CohortItem, cohort_item_id)
    if not item or not db.get(ProjectDataset, (project_id, item.dataset_id)):
        raise HTTPException(422, "Select a cohort item from a dataset linked to this project")
    existing = db.scalar(select(CaseSourceLink).where(CaseSourceLink.project_id == project_id,
                         CaseSourceLink.cohort_item_id == cohort_item_id))
    if existing:
        raise HTTPException(409, "Images are already linked to this cohort item; existing annotations were preserved")
    dataset = db.get(CatalogDataset, item.dataset_id)
    return item, dataset
