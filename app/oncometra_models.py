"""Workspace metadata separated from the existing image/annotation engine."""

from datetime import datetime
from uuid import uuid4
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, UniqueConstraint, Text, Integer, Boolean, Index, text
from app.db import Base


def uid():
    return str(uuid4())


class WorkspaceUser(Base):
    __tablename__ = "workspace_users"
    id = Column(String(36), primary_key=True, default=uid)
    username = Column(String(80), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(30), nullable=False)
    projects = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WorkspaceSession(Base):
    __tablename__ = "workspace_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey("workspace_users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class WorkspaceCase(Base):
    __tablename__ = "workspace_cases"
    id = Column(String(36), primary_key=True, default=uid)
    project_id = Column(String(40), index=True, nullable=False)
    patient_id = Column(String(100), nullable=False)
    modality = Column(String(8), nullable=False)
    source = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("project_id", "patient_id"),)


class WorkspaceAssignment(Base):
    __tablename__ = "workspace_assignments"
    study_id = Column(String(36), ForeignKey("studies.id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("workspace_cases.id"), index=True, nullable=False)
    user_id = Column(String(36), ForeignKey("workspace_users.id"), index=True, nullable=False)
    kind = Column(String(20), default="reader", nullable=False)
    provenance = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("case_id", "user_id", "kind"),)


class WorkspaceFeatureJob(Base):
    __tablename__ = "workspace_feature_jobs"
    id = Column(String(36), primary_key=True, default=uid)
    study_id = Column(String(36), ForeignKey("studies.id"), index=True, nullable=False)
    user_id = Column(String(36), nullable=False)
    revision_id = Column(String(36), nullable=False)
    status = Column(String(20), default="queued", nullable=False)
    protocol = Column(JSON, nullable=False)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WorkspaceAudit(Base):
    __tablename__ = "workspace_audit"
    id = Column(String(36), primary_key=True, default=uid)
    user_id = Column(String(36), nullable=False)
    action = Column(String(60), nullable=False)
    subject_id = Column(String(36))
    details = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WorkspaceProject(Base):
    __tablename__ = "workspace_projects"
    id = Column(String(40), primary_key=True, default=uid)
    name = Column(String(120), nullable=False)
    cancer_origin = Column(String(120), nullable=False)
    modality = Column(String(8), nullable=False)
    target = Column(String(300), nullable=False)
    guidelines = Column(Text, nullable=False, default="")
    lesion_sites = Column(JSON, nullable=False, default=list)
    color = Column(String(7), nullable=False, default="#0a5ad4")
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CatalogDataset(Base):
    __tablename__ = "catalog_datasets"
    id = Column(String(36), primary_key=True, default=uid)
    registry = Column(String(80), nullable=False)
    external_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    url = Column(Text, nullable=False)
    tumor_types = Column(JSON, nullable=False, default=list)
    modalities = Column(JSON, nullable=False, default=list)
    access = Column(String(32), nullable=False, default="unknown")
    license_name = Column(String(255), nullable=False, default="Unverified")
    license_url = Column(Text, nullable=False, default="")
    commercial_use = Column(String(32), nullable=False, default="unknown")
    longitudinal = Column(Boolean, nullable=True)
    segmentations = Column(Boolean, nullable=True)
    status = Column(String(32), nullable=False, default="identified")
    notes = Column(Text, nullable=False, default="")
    evidence = Column(JSON, nullable=False, default=list)
    source_snapshot = Column(JSON, nullable=False, default=dict)
    version = Column(Integer, nullable=False, default=1)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    dicom_ready = Column(Boolean, nullable=False, default=False, server_default=text("0"))
    dicom_path = Column(Text, nullable=False, default="", server_default="")
    indexed_patients = Column(Integer, nullable=False, default=0, server_default=text("0"))
    tumor_detail = Column(Text, nullable=False, default="", server_default="")
    totalseg_status = Column(String(16), nullable=False, default="", server_default="")
    totalseg_error = Column(Text, nullable=False, default="", server_default="")
    totalseg_detail = Column(Text, nullable=False, default="", server_default="")
    totalseg_at = Column(DateTime)
    __table_args__ = (UniqueConstraint("registry", "external_id", name="uq_catalog_source"),)


class CatalogPatientIndex(Base):
    """Patient and visit index copied from OncoRadar. OncoSeG does not rebuild it."""
    __tablename__ = "catalog_patient_index"
    id = Column(String(36), primary_key=True, default=uid)
    dataset_id = Column(String(36), ForeignKey("catalog_datasets.id"), nullable=False, index=True)
    source_id = Column(String(128), nullable=False)
    study_dates = Column(JSON, nullable=False, default=list)
    totalseg = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    __table_args__ = (UniqueConstraint("dataset_id", "source_id", name="uq_catalog_patient_source"),)


class ProjectDataset(Base):
    __tablename__ = "project_datasets"
    project_id = Column(String(40), ForeignKey("workspace_projects.id"), primary_key=True)
    dataset_id = Column(String(36), ForeignKey("catalog_datasets.id"), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CohortItem(Base):
    __tablename__ = "cohort_items"
    id = Column(String(36), primary_key=True, default=uid)
    dataset_id = Column(String(36), ForeignKey("catalog_datasets.id"), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    patient_id = Column(String(120), nullable=False)
    study_uid = Column(String(64), nullable=False, default="")
    series_uid = Column(String(64), nullable=False, default="")
    modality = Column(String(8), nullable=False)
    visit = Column(String(120), nullable=False, default="")
    metadata_json = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("dataset_id", "external_id", name="uq_cohort_source"),)


class CaseSourceLink(Base):
    __tablename__ = "case_source_links"
    case_id = Column(String(36), ForeignKey("workspace_cases.id"), primary_key=True)
    project_id = Column(String(40), ForeignKey("workspace_projects.id"), nullable=False)
    cohort_item_id = Column(String(36), ForeignKey("cohort_items.id"), nullable=False)
    __table_args__ = (UniqueConstraint("project_id", "cohort_item_id", name="uq_project_cohort_image"),)


class CatalogJob(Base):
    __tablename__ = "catalog_jobs"
    id = Column(String(36), primary_key=True, default=uid)
    registry = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    requested_by = Column(String(36), ForeignKey("workspace_users.id"), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    lease_token = Column(String(36))
    lease_until = Column(DateTime)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime)
    __table_args__ = (Index("uq_catalog_active_registry", "registry", unique=True,
        sqlite_where=text("status IN ('queued', 'running')")),)
