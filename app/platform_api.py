"""Unified catalog, cohort and project API using the existing workspace identity."""

from datetime import datetime
import json
import threading
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, update, cast, literal, Text, JSON
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal
from app.oncometra_models import (
    WorkspaceProject, WorkspaceUser, WorkspaceCase, CatalogDataset, CatalogPatientIndex, ProjectDataset,
    CohortItem, CaseSourceLink, CatalogJob,
)
from app.platform_services import (
    apply_imaging_index, dataset_payload, project_payload, safe_url, upsert_discovery,
    validate_cohort_identity, visible_projects,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProjectInput(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    cancer_origin: str = Field(min_length=2, max_length=120)
    modality: Literal["CT", "MR"]
    target: str = Field(min_length=2, max_length=300)
    guidelines: str = Field(min_length=10, max_length=20000)
    lesion_sites: list[str] = Field(default_factory=list, max_length=40)
    color: str = Field(default="#0a5ad4", pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("lesion_sites")
    @classmethod
    def sites(cls, value):
        if any(not item.strip() or len(item) > 120 for item in value):
            raise ValueError("Lesion site labels must contain 1-120 characters")
        return list(dict.fromkeys(item.strip() for item in value))


class ProjectUpdate(ProjectInput):
    version: int = Field(ge=1)


class Membership(StrictModel):
    enabled: bool


class Evidence(StrictModel):
    field: str = Field(min_length=1, max_length=80)
    url: str = Field(max_length=2048)
    quote: str = Field(min_length=1, max_length=2000)

    @field_validator("url")
    @classmethod
    def url_valid(cls, value):
        return safe_url(value)


class DatasetFields(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    url: str = Field(max_length=2048)
    tumor_types: list[str] = Field(default_factory=list, max_length=40)
    modalities: list[Literal["CT", "MR"]] = Field(default_factory=list, max_length=2)
    access: Literal["unknown", "direct", "login", "account", "request"] = "unknown"
    license_name: str = Field(default="Unverified", max_length=255)
    license_url: str = Field(default="", max_length=2048)
    commercial_use: Literal["unknown", "permitted", "noncommercial", "permission_required"] = "unknown"
    longitudinal: bool | None = None
    segmentations: bool | None = None
    notes: str = Field(default="", max_length=10000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=30)

    @field_validator("url", "license_url")
    @classmethod
    def urls(cls, value, info):
        return safe_url(value, empty=info.field_name == "license_url")

    @field_validator("tumor_types")
    @classmethod
    def cancers(cls, value):
        if any(not item.strip() or len(item) > 120 for item in value):
            raise ValueError("Cancer labels must contain 1-120 characters")
        return list(dict.fromkeys(item.strip() for item in value))


class DatasetInput(DatasetFields):
    registry: str = Field(default="Manual", min_length=1, max_length=80)
    external_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=255)


class DatasetUpdate(DatasetFields):
    version: int = Field(ge=1)
    status: Literal["identified", "contacted", "access_requested", "downloaded"] = "identified"


class CatalogImport(StrictModel):
    records: list[dict] = Field(min_length=1, max_length=500)


class CohortRecord(StrictModel):
    external_id: str = Field(min_length=1, max_length=255)
    patient_id: str = Field(min_length=1, max_length=120)
    modality: Literal["CT", "MR"]
    study_uid: str = Field(default="", max_length=64, pattern=r"^[0-9.]*$")
    series_uid: str = Field(default="", max_length=64, pattern=r"^[0-9.]*$")
    visit: str = Field(default="", max_length=120)
    metadata: dict = Field(default_factory=dict)


class CohortImport(StrictModel):
    deidentified: Literal[True]
    records: list[CohortRecord] = Field(min_length=1, max_length=5000)


class LinkDataset(StrictModel):
    dataset_id: UUID


class DiscoveryRequest(StrictModel):
    registry: Literal["TCIA", "IDC"]


class OncoRadarSync(StrictModel):
    database: str = Field(min_length=1, max_length=1024)


def job_payload(row):
    return {"id": row.id, "registry": row.registry, "status": row.status,
            "attempts": row.attempts, "result": row.result, "error": row.error,
            "created_at": row.created_at.isoformat()}


_ACCESS_CODE = {"Direct download": "direct", "Login required": "login", "Account required": "account", "Request access": "request"}
_REGISTRY_OPEN = {
    "IDC": "Direct download", "TCIA": "Account required", "OpenNeuro": "Account required",
    "ISIC Archive": "Account required", "Zenodo": "Direct download", "MSD": "Direct download",
    "Hugging Face": "Direct download", "Grand Challenge": "Account required", "GDC": "Request access",
    "HTAN": "Request access",
}
_REGISTRY_MIXED = {
    "TCIA": "Request access", "GDC": "Request access", "HTAN": "Request access",
    "Hugging Face": "Request access", "IDC": "Request access", "ISIC Archive": "Account required",
    "OpenNeuro": "Account required", "Zenodo": "Direct download",
}


def oncoradar_access(value, registry=""):
    """Same download labels as OncoRadar. An open TCIA collection still needs an account."""
    text = str(value or "").strip()
    if text in _ACCESS_CODE:
        return _ACCESS_CODE[text]
    lowered = text.lower()
    wording = [
        (("direct download", "download directly", "downloadable", "publicly available", "open access", "freely available"), "Direct download"),
        (("login", "log in", "sign in", "credentials", "authentication"), "Login required"),
        (("account", "register", "create an account", "signup", "sign up"), "Account required"),
        (("request access", "access request", "apply", "approval", "email", "contact", "by request"), "Request access"),
    ]
    label = next((name for tokens, name in wording if any(token in lowered for token in tokens)), "")
    if not label:
        folded = " ".join(text.replace("\u00a0", " ").replace("–", "-").replace("—", "-").replace("·", " ").replace(".", " ").lower().split())
        if "gated" in folded or "restricted" in folded:
            label = "Request access"
        elif "mixed" in folded:
            label = _REGISTRY_MIXED.get(registry, "Request access")
        elif folded in {"open", "mostly open"} or folded.startswith("open "):
            label = _REGISTRY_OPEN.get(registry, "")
    return _ACCESS_CODE.get(label, "unknown")


def oncoradar_commercial(raw):
    """Copy OncoRadar's Allowed / Not allowed. An empty cell stays unknown."""
    text = str(raw.get("commercial_use") or raw.get("commercial") or "").strip().lower().replace("_", " ").replace("-", " ")
    if text in {"allowed", "permitted"}:
        return "permitted"
    if text in {"not allowed", "noncommercial", "non commercial"}:
        return "noncommercial"
    if text in {"permission required"}:
        return "permission_required"
    return "unknown"


def apply_imported_rights(row, fields):
    """Fill rights that were never reviewed. A curator value is left as stored."""
    if row.commercial_use == "unknown" and fields["commercial_use"] != "unknown":
        row.commercial_use = fields["commercial_use"]
    if row.license_name in ("", "Unverified") and fields["license_name"] not in ("", "Unverified"):
        row.license_name = fields["license_name"]
    if row.access == "unknown" and fields["access"] != "unknown":
        row.access = fields["access"]


def normalize_oncoradar(raw):
    source = str(raw.get("registry") or "OncoRadar")
    name = str(raw.get("name") or "")
    url = str(raw.get("url") or "")
    modalities = raw.get("modalities") or []
    if isinstance(modalities, str):
        modalities = [modalities]
    notes = raw.get("notes") or ""
    if isinstance(notes, list):
        notes = "\n".join(str(item) for item in notes)
    tumor = raw.get("tumor_types") or raw.get("tumor") or []
    if isinstance(tumor, str):
        tumor = [tumor]
    # OncoRadar stores a free-text description here, not a short label.
    tumor = list(dict.fromkeys(" ".join(str(item).split())[:120] for item in tumor if str(item).strip()))[:40]
    segmentation_count = raw.get("seg")
    has_segmentations = (raw.get("segmentations") is True or
        isinstance(segmentation_count, int) and segmentation_count > 0)
    license_name = str(raw.get("license_name") or raw.get("license") or "Unverified").strip()[:255] or "Unverified"
    # OncoRadar's false booleans also mean "not established". Do not turn them into verified negatives.
    return DatasetInput.model_validate({"registry": source, "external_id": str(raw.get("external_id") or raw.get("id") or name),
        "name": name, "url": url, "tumor_types": tumor,
        "modalities": sorted({"MR" if str(v).upper() == "MRI" else str(v).upper() for v in modalities} & {"CT", "MR"}),
        "access": oncoradar_access(raw.get("access"), source), "license_name": license_name,
        "license_url": raw.get("license_url") or "", "commercial_use": oncoradar_commercial(raw),
        "longitudinal": True if raw.get("longitudinal") in (True, 1) else None,
        "segmentations": True if has_segmentations else None,
        "notes": notes, "evidence": raw.get("evidence") or []}).model_dump()


def build_router(current_user, require_admin, require_project, audit):
    router = APIRouter(prefix="/api")

    @router.post("/oncoradar-sync")
    def sync_oncoradar(req: OncoRadarSync, user=Depends(current_user)):
        require_admin(user)
        from app.oncoradar_import import read_oncoradar
        try:
            payload = read_oncoradar(req.database)
            pairs = [(normalize_oncoradar(row), row) for row in payload["records"]]
        except (ValueError, TypeError, json.JSONDecodeError, OSError) as error:
            message = str(error)
            status = 404 if "not found" in message.lower() else 422
            raise HTTPException(status, message) from error
        if not pairs:
            raise HTTPException(422, "OncoRadar database has no datasets")
        with SessionLocal() as db:
            created = 0
            patients = 0
            try:
                for fields, raw in pairs:
                    row, was_created = upsert_discovery(db, fields)
                    created += was_created
                    patients += apply_imaging_index(db, row, raw)
                    apply_imported_rights(row, fields)
            except (ValueError, TypeError) as error:
                db.rollback()
                raise HTTPException(422, str(error)) from error
            audit(db, user, "oncoradar_index_synced", details={
                "created": created, "refreshed": len(pairs) - created, "patients": patients,
            })
            db.commit()
            return {"created": created, "refreshed": len(pairs) - created, "patients": patients,
                    "datasets": len(pairs)}

    @router.get("/projects")
    def projects(user=Depends(current_user)):
        with SessionLocal() as db:
            return [project_payload(row) for row in visible_projects(db, user)]

    @router.post("/projects", status_code=201)
    def create_project(req: ProjectInput, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            row = WorkspaceProject(id=str(uuid4()), **req.model_dump())
            db.add(row)
            db.flush()
            audit(db, user, "project_created", row.id, project_payload(row))
            db.commit()
            return project_payload(row)

    @router.put("/projects/{project_id}")
    def edit_project(project_id: str, req: ProjectUpdate, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            row = db.get(WorkspaceProject, project_id)
            if not row:
                raise HTTPException(404, "Project not found")
            if row.modality != req.modality and db.scalar(select(WorkspaceCase.id).where(WorkspaceCase.project_id == project_id).limit(1)):
                raise HTTPException(409, "Cannot change modality after images are imported; create a separate project")
            before = project_payload(row)
            result = db.execute(update(WorkspaceProject).where(WorkspaceProject.id == project_id, WorkspaceProject.version == req.version)
                .values(**req.model_dump(exclude={"version"}), version=req.version + 1))
            if result.rowcount != 1:
                raise HTTPException(409, "Project changed. Reload before saving.")
            audit(db, user, "project_updated", project_id, {"before": before, "after": req.model_dump(), "version": req.version + 1})
            db.commit()
            db.refresh(row)
            return project_payload(row)

    @router.get("/projects/{project_id}/members")
    def members(project_id: str, user=Depends(current_user)):
        require_admin(user)
        require_project(user, project_id)
        with SessionLocal() as db:
            return [{"id": member.id, "name": member.name, "role": member.role,
                     "enabled": member.role == "admin" or project_id in member.projects}
                    for member in db.scalars(select(WorkspaceUser).order_by(WorkspaceUser.name))]

    @router.put("/projects/{project_id}/members/{user_id}")
    def membership(project_id: str, user_id: UUID, req: Membership, user=Depends(current_user)):
        require_admin(user)
        require_project(user, project_id)
        with SessionLocal() as db:
            target = db.get(WorkspaceUser, str(user_id))
            if not target:
                raise HTTPException(404, "Account not found")
            if target.role == "admin":
                raise HTTPException(409, "Administrators have workspace-wide project access")
            previous = list(target.projects)
            updated = sorted(set(previous + [project_id])) if req.enabled else [p for p in previous if p != project_id]
            changed = db.execute(update(WorkspaceUser).where(WorkspaceUser.id == target.id,
                cast(WorkspaceUser.projects, Text) == cast(literal(previous, type_=JSON), Text)).values(projects=updated))
            if changed.rowcount != 1:
                raise HTTPException(409, "Membership changed concurrently. Reload and retry.")
            audit(db, user, "project_membership_changed", project_id, {"user_id": target.id, "enabled": req.enabled})
            db.commit()
            return {"ok": True}

    @router.get("/catalog")
    def catalog(q: str = "", modality: Literal["", "CT", "MR"] = "", status: str = "",
                scope: Literal["", "eligible", "all"] = "",
                commercial_use: Literal["", "permitted", "noncommercial", "permission_required", "unknown"] = "",
                access: Literal["", "direct", "login", "account", "request", "unknown"] = "",
                registry: str = Query("", max_length=80),
                masks: Literal["", "yes", "no", "unknown"] = "",
                followup: Literal["", "yes", "no", "unknown"] = "",
                images: Literal["", "ready", "missing"] = "",
                license: Literal["", "named", "unverified"] = "",
                page: int = Query(1, ge=1), user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            query = select(CatalogDataset)
            if q:
                query = query.where(CatalogDataset.name.ilike("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%", escape="\\"))
            if status:
                query = query.where(CatalogDataset.status == status)
            if scope == "eligible":
                query = query.where(CatalogDataset.commercial_use == "permitted", CatalogDataset.access == "direct")
            if commercial_use:
                query = query.where(CatalogDataset.commercial_use == commercial_use)
            if access:
                query = query.where(CatalogDataset.access == access)
            if registry:
                query = query.where(CatalogDataset.registry == registry)
            if masks == "yes":
                query = query.where(CatalogDataset.segmentations.is_(True))
            elif masks == "no":
                query = query.where(CatalogDataset.segmentations.is_(False))
            elif masks == "unknown":
                query = query.where(CatalogDataset.segmentations.is_(None))
            if followup == "yes":
                query = query.where(CatalogDataset.longitudinal.is_(True))
            elif followup == "no":
                query = query.where(CatalogDataset.longitudinal.is_(False))
            elif followup == "unknown":
                query = query.where(CatalogDataset.longitudinal.is_(None))
            if images == "ready":
                query = query.where(CatalogDataset.dicom_ready.is_(True))
            elif images == "missing":
                query = query.where(CatalogDataset.dicom_ready.is_(False))
            if license == "named":
                query = query.where(CatalogDataset.license_name.notin_(["", "Unverified"]))
            elif license == "unverified":
                query = query.where(CatalogDataset.license_name.in_(["", "Unverified"]))
            # Portable JSON containment is implemented after a bounded metadata selection.
            if modality:
                from sqlalchemy import cast, String
                query = query.where(cast(CatalogDataset.modalities, String).contains('"' + modality + '"'))
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            rows = list(db.scalars(query.order_by(CatalogDataset.name).offset((page - 1) * 50).limit(50)))
            return {"items": [dataset_payload(row) for row in rows], "total": total, "page": page, "page_size": 50}

    @router.post("/catalog/{dataset_id}/use")
    def use_dataset(dataset_id: UUID, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, str(dataset_id))
            if not dataset:
                raise HTTPException(404, "Dataset not found")
            project = None
            for link in db.scalars(select(ProjectDataset).where(ProjectDataset.dataset_id == dataset.id)):
                project = db.get(WorkspaceProject, link.project_id)
                if project:
                    break
            created = project is None
            if created:
                modalities = [str(item).upper() for item in (dataset.modalities or [])]
                modality = "CT" if "CT" in modalities or "MR" not in modalities else "MR"
                name = (dataset.name or "Cohorte").strip()[:120] or "Cohorte"
                if len(name) < 2:
                    name = "Cohorte"
                origin = (", ".join(dataset.tumor_types or []) or name)[:120]
                if len(origin) < 2:
                    origin = "Cohorte"
                project = WorkspaceProject(
                    id=str(uuid4()), name=name, cancer_origin=origin, modality=modality, target=name[:300],
                    guidelines="Annoter les lésions visibles sur les séries importées. Corriger la proposition du modèle lorsqu'elle existe, sinon dessiner le masque.",
                    lesion_sites=[], color="#0a5ad4")
                db.add(project)
                db.flush()
                db.add(ProjectDataset(project_id=project.id, dataset_id=dataset.id))
                audit(db, user, "dataset_opened_as_cohort", project.id, {"dataset_id": dataset.id})
            for account in db.scalars(select(WorkspaceUser)):
                if account.role == "admin":
                    continue
                previous = list(account.projects or [])
                if project.id not in previous:
                    db.execute(update(WorkspaceUser).where(WorkspaceUser.id == account.id).values(projects=previous + [project.id]))
            case_count = db.scalar(select(func.count()).select_from(WorkspaceCase).where(WorkspaceCase.project_id == project.id)) or 0
            gaps = []
            if dataset.commercial_use != "permitted":
                gaps.append("licence non tranchée")
            if not case_count:
                gaps.append("images non importées")
            if dataset.segmentations is not True:
                gaps.append("pas de masque")
            db.commit()
            return JSONResponse({"project_id": project.id, "name": project.name, "created": created, "gaps": gaps},
                                status_code=201 if created else 200)

    @router.post("/catalog", status_code=201)
    def create_dataset(req: DatasetInput, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            row, created = upsert_discovery(db, req.model_dump())
            if not created:
                raise HTTPException(409, "That source already exists. Use its edit form; no curation was overwritten.")
            audit(db, user, "dataset_created", row.id)
            db.commit()
            return dataset_payload(row)

    @router.put("/catalog/{dataset_id}")
    def edit_dataset(dataset_id: UUID, req: DatasetUpdate, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            row = db.get(CatalogDataset, str(dataset_id))
            if not row:
                raise HTTPException(404, "Dataset not found")
            previous = dataset_payload(row)
            changed = db.execute(update(CatalogDataset).where(CatalogDataset.id == str(dataset_id), CatalogDataset.version == req.version)
                .values(**req.model_dump(exclude={"version"}), version=req.version + 1))
            if changed.rowcount != 1:
                raise HTTPException(409, "Dataset changed. Reload before saving.")
            audit(db, user, "dataset_curated", row.id, {"before": previous, "after": req.model_dump()})
            db.commit()
            db.refresh(row)
            return dataset_payload(row)

    @router.post("/catalog-import")
    def import_catalog(req: CatalogImport, user=Depends(current_user)):
        require_admin(user)
        if len(json.dumps(req.records)) > 4_000_000:
            raise HTTPException(413, "Catalog import exceeds 4 MB")
        try:
            pairs = [(normalize_oncoradar(row), row) for row in req.records]
        except (ValueError, TypeError) as error:
            raise HTTPException(422, str(error)) from error
        with SessionLocal() as db:
            created = 0
            patients = 0
            try:
                for fields, raw in pairs:
                    row, was_created = upsert_discovery(db, fields)
                    created += was_created
                    patients += apply_imaging_index(db, row, raw)
                    apply_imported_rights(row, fields)
            except (ValueError, TypeError) as error:
                db.rollback()
                raise HTTPException(422, str(error)) from error
            audit(db, user, "catalog_imported", details={"created": created, "refreshed": len(pairs) - created, "patients": patients})
            db.commit()
            return {"created": created, "refreshed": len(pairs) - created, "patients": patients}

    def _totalseg_payload(db, dataset, page):
        from app.services.totalseg_stats import installed, lesion_line, ready
        query = select(CatalogPatientIndex).where(CatalogPatientIndex.dataset_id == dataset.id)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = list(db.scalars(query.order_by(CatalogPatientIndex.source_id).offset((page - 1) * 20).limit(20)))
        items = []
        for row in rows:
            visits = []
            for item in row.totalseg or []:
                if not isinstance(item, dict):
                    continue
                visits.append({"date": item.get("timepoint") or "", "organs": item.get("organs") or "",
                               "lesion": lesion_line(item), "quote": item.get("quote") or ""})
            items.append({"source_id": row.source_id, "study_dates": row.study_dates, "visits": visits})
        return {"status": dataset.totalseg_status or "", "detail": dataset.totalseg_detail or "",
                "error": dataset.totalseg_error or "", "ready": ready(dataset), "installed": installed(),
                "dicom_path": dataset.dicom_path or "", "total": total, "page": page, "page_size": 20, "items": items}

    @router.get("/catalog/{dataset_id}/totalseg")
    def totalseg_status(dataset_id: UUID, page: int = Query(1, ge=1), user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, str(dataset_id))
            if not dataset:
                raise HTTPException(404, "Dataset not found")
            return _totalseg_payload(db, dataset, page)

    @router.post("/catalog/{dataset_id}/totalseg", status_code=202)
    def totalseg_start(dataset_id: UUID, user=Depends(current_user)):
        require_admin(user)
        from app.services.totalseg_stats import TotalsegError, execute, installed, ready
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, str(dataset_id))
            if not dataset:
                raise HTTPException(404, "Dataset not found")
            if dataset.totalseg_status == "running":
                return _totalseg_payload(db, dataset, 1)
            if not ready(dataset):
                raise HTTPException(422, "This dataset needs a local DICOM folder and an indexed patient list.")
            if not installed():
                raise HTTPException(503, "TotalSegmentator is not installed or not on PATH.")
            dataset.totalseg_status = "running"
            dataset.totalseg_error = ""
            dataset.totalseg_detail = "Starting…"
            audit(db, user, "totalseg_started", dataset.id, {"dicom_path": dataset.dicom_path})
            db.commit()
            payload = _totalseg_payload(db, dataset, 1)
        def _job():
            try:
                execute(str(dataset_id))
            except TotalsegError:
                return
            except Exception:
                return
        threading.Thread(target=_job, daemon=True).start()
        return payload

    @router.post("/catalog/{dataset_id}/totalseg/stop")
    def totalseg_stop(dataset_id: UUID, user=Depends(current_user)):
        require_admin(user)
        from app.services.totalseg_stats import stop_running
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, str(dataset_id))
            if not dataset:
                raise HTTPException(404, "Dataset not found")
            if dataset.totalseg_status == "running":
                dataset.totalseg_status = "done"
                dataset.totalseg_detail = "Stopped."
                audit(db, user, "totalseg_stopped", dataset.id)
                db.commit()
            stop_running()
            return _totalseg_payload(db, dataset, 1)

    @router.get("/catalog/{dataset_id}/patient-index")
    def patient_index(dataset_id: UUID, page: int = Query(1, ge=1), user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            dataset = db.get(CatalogDataset, str(dataset_id))
            if not dataset:
                raise HTTPException(404, "Dataset not found")
            query = select(CatalogPatientIndex).where(CatalogPatientIndex.dataset_id == dataset.id)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            rows = list(db.scalars(query.order_by(CatalogPatientIndex.source_id).offset((page - 1) * 50).limit(50)))
            return {"dicom_ready": bool(dataset.dicom_ready), "dicom_path": dataset.dicom_path,
                    "total": total, "page": page, "page_size": 50,
                    "items": [{"source_id": row.source_id, "study_dates": row.study_dates} for row in rows]}

    @router.post("/catalog-jobs", status_code=202)
    def discover(req: DiscoveryRequest, user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            active = db.scalar(select(CatalogJob).where(CatalogJob.registry == req.registry, CatalogJob.status.in_(["queued", "running"])))
            if active:
                return job_payload(active)
            row = CatalogJob(registry=req.registry, requested_by=user.id)
            db.add(row)
            try:
                db.flush()
                audit(db, user, "catalog_discovery_queued", row.id, {"registry": row.registry})
                db.commit()
            except IntegrityError:
                db.rollback()
                active = db.scalar(select(CatalogJob).where(CatalogJob.registry == req.registry,
                    CatalogJob.status.in_(["queued", "running"])))
                if active:
                    return job_payload(active)
                raise HTTPException(409, "Discovery queue changed. Refresh and retry.")
            return job_payload(row)

    @router.get("/catalog-jobs")
    def jobs(user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            return [job_payload(row) for row in db.scalars(select(CatalogJob).order_by(CatalogJob.created_at.desc()).limit(20))]

    @router.post("/projects/{project_id}/datasets")
    def link_dataset(project_id: str, req: LinkDataset, user=Depends(current_user)):
        require_admin(user)
        require_project(user, project_id)
        with SessionLocal() as db:
            dataset_id = str(req.dataset_id)
            if not db.get(CatalogDataset, dataset_id):
                raise HTTPException(404, "Dataset not found")
            if not db.get(ProjectDataset, (project_id, dataset_id)):
                db.add(ProjectDataset(project_id=project_id, dataset_id=dataset_id))
                audit(db, user, "dataset_linked_to_project", project_id, {"dataset_id": dataset_id})
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
            return {"ok": True}

    @router.get("/catalog/{dataset_id}/cohort")
    def cohort(dataset_id: UUID, project_id: str = "", page: int = Query(1, ge=1), user=Depends(current_user)):
        require_admin(user)
        with SessionLocal() as db:
            query = select(CohortItem).where(CohortItem.dataset_id == str(dataset_id))
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            rows = list(db.scalars(query.order_by(CohortItem.patient_id, CohortItem.external_id).offset((page - 1) * 50).limit(50)))
            links = {row.cohort_item_id: row.case_id for row in db.scalars(select(CaseSourceLink).where(
                CaseSourceLink.cohort_item_id.in_([r.id for r in rows]), CaseSourceLink.project_id == project_id))} if project_id else {}
            return {"total": total, "page": page, "items": [{"id": row.id, "external_id": row.external_id,
                "patient_id": row.patient_id, "modality": row.modality, "study_uid": row.study_uid, "series_uid": row.series_uid,
                "visit": row.visit, "case_id": links.get(row.id)} for row in rows]}

    @router.post("/catalog/{dataset_id}/cohort")
    def import_cohort(dataset_id: UUID, req: CohortImport, user=Depends(current_user)):
        require_admin(user)
        if len(req.model_dump_json()) > 4_000_000:
            raise HTTPException(413, "Cohort manifest exceeds 4 MB")
        identifiers = [row.external_id for row in req.records]
        if len(set(identifiers)) != len(identifiers):
            raise HTTPException(422, "Duplicate external_id in manifest; use one stable ID per imaging series")
        with SessionLocal() as db:
            if not db.get(CatalogDataset, str(dataset_id)):
                raise HTTPException(404, "Dataset not found")
            created = 0
            for item in req.records:
                record = item.model_dump()
                row = db.scalar(select(CohortItem).where(CohortItem.dataset_id == str(dataset_id), CohortItem.external_id == item.external_id))
                if row:
                    validate_cohort_identity(row, record)
                    row.visit, row.metadata_json, row.updated_at = item.visit, item.metadata, datetime.utcnow()
                else:
                    row = CohortItem(dataset_id=str(dataset_id), **{k: v for k, v in record.items() if k != "metadata"}, metadata_json=item.metadata)
                    db.add(row)
                    created += 1
            audit(db, user, "cohort_manifest_imported", str(dataset_id), {"created": created, "refreshed": len(req.records) - created})
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raise HTTPException(409, "Cohort changed concurrently. Refresh and retry; no part of this batch was published.")
            return {"created": created, "refreshed": len(req.records) - created, "images_downloaded": False}

    @router.get("/projects/{project_id}/manifest")
    def export_manifest(project_id: str, user=Depends(current_user)):
        require_project(user, project_id)
        with SessionLocal() as db:
            project = db.get(WorkspaceProject, project_id)
            links = list(db.scalars(select(ProjectDataset).where(ProjectDataset.project_id == project_id)))
            cases = list(db.scalars(select(WorkspaceCase).where(WorkspaceCase.project_id == project_id)))
            # No filesystem paths, session data or other readers' masks are exposed.
            manifest = {"schema": "oncometra.project-manifest.v1", "project": project_payload(project),
                "datasets": [dataset_payload(db.get(CatalogDataset, link.dataset_id)) for link in links],
                "cases": [{"id": row.id, "patient_id": row.patient_id, "modality": row.modality,
                           "source": row.source} for row in cases]}
            audit(db, user, "project_manifest_exported", project_id)
            db.commit()
            return JSONResponse(manifest, headers={"Content-Disposition": f'attachment; filename="project-{project_id}.json"'})

    return router
