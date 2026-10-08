"""Unified workflow regression tests. Synthetic data; no external network calls."""

from datetime import datetime, timedelta
import json
from uuid import uuid4

from sqlalchemy import select, update

from test_oncometra import clients, isolated_login_limits, fixture_case, assigned, complete
from app.oncometra import SessionLocal, image_directory, seed_demo
from app.oncometra_models import (
    WorkspaceAssignment, WorkspaceCase, WorkspaceProject, CatalogDataset, CatalogPatientIndex,
    CohortItem, CaseSourceLink, CatalogJob,
)
from app.models import AnnotationHead
from app.catalog_worker import run_once


def project_request(**overrides):
    return {"name": "Melanoma response cohort", "cancer_origin": "Melanoma", "modality": "CT",
            "target": "Primary tumor and metastases", "lesion_sites": ["Lung", "Liver", "Lymph nodes"],
            "guidelines": "Contour each measurable lesion independently. Review every involved slice.", **overrides}


def dataset_request(**overrides):
    return {"registry": "Test", "external_id": "SYNTHETIC", "name": "Synthetic source",
            "url": "https://example.org/dataset", "modalities": ["CT"], "tumor_types": ["Melanoma"], **overrides}


def add_dataset(admin):
    response = admin.post('/api/catalog', json=dataset_request())
    assert response.status_code == 201, response.text
    return response.json()


def add_cohort(admin, dataset_id):
    record = {"external_id": "PATIENT-1/BASELINE/CT", "patient_id": "PSEUDONYM-1",
              "modality": "CT", "visit": "baseline"}
    response = admin.post(f'/api/catalog/{dataset_id}/cohort', json={"deidentified": True, "records": [record]})
    assert response.status_code == 200, response.text
    return record, admin.get(f'/api/catalog/{dataset_id}/cohort').json()['items'][0]


def test_projects_are_admin_created_private_and_restart_safe(clients):
    admin, reader, reviewer = clients
    assert reader.post('/api/projects', json=project_request()).status_code == 403
    assert reviewer.post('/api/projects', json=project_request()).status_code == 403
    result = admin.post('/api/projects', json=project_request())
    assert result.status_code == 201, result.text
    project = result.json()
    assert project['id'] in [p['id'] for p in admin.get('/api/workspace').json()['projects']]
    assert project['id'] not in [p['id'] for p in reader.get('/api/projects').json()]
    assert reader.get(f'/api/projects/{project["id"]}/manifest').status_code == 403
    reader_id = reader.get('/api/auth/me').json()['id']
    member_url = f'/api/projects/{project["id"]}/members/{reader_id}'
    assert reader.put(member_url, json={"enabled": True}).status_code == 403
    assert admin.put(member_url, json={"enabled": True}).status_code == 200
    assert project['id'] in [p['id'] for p in reader.get('/api/projects').json()]
    seed_demo()
    assert project['id'] in [p['id'] for p in reader.get('/api/projects').json()]
    assert admin.put(member_url, json={"enabled": False}).status_code == 200
    assert reader.get(f'/api/projects/{project["id"]}/manifest').status_code == 403


def test_guidelines_are_snapshotted_without_replacing_existing_work(clients):
    admin, reader, _ = clients
    case = fixture_case()
    study_id = assigned(reader, case)
    before = next(p for p in admin.get('/api/projects').json() if p['id'] == 'lung-ct')
    updated = {k: v for k, v in before.items() if k != 'id'}
    updated['guidelines'] = 'New protocol: annotate lung, liver, and nodal lesions separately.'
    response = admin.put('/api/projects/lung-ct', json=updated)
    assert response.status_code == 200, response.text
    assert response.json()['version'] == before['version'] + 1
    assert admin.put('/api/projects/lung-ct', json=updated).status_code == 409
    with SessionLocal() as db:
        assignment = db.get(WorkspaceAssignment, study_id)
        assert assignment.provenance['guidelines'] == before['guidelines']
        assert assignment.provenance['project_version'] == before['version']
    seed_demo()
    assert next(p for p in admin.get('/api/projects').json() if p['id'] == 'lung-ct')['guidelines'] == updated['guidelines']


def test_catalog_permissions_tristate_validation_and_optimistic_edits(clients):
    admin, reader, reviewer = clients
    for client in (reader, reviewer):
        assert client.get('/api/catalog').status_code == 403
        assert client.post('/api/catalog-jobs', json={"registry": "TCIA"}).status_code == 403
    assert admin.post('/api/catalog', json=dataset_request(url='javascript:alert(1)')).status_code == 422
    assert admin.post('/api/catalog', json=dataset_request(modalities=['US'])).status_code == 422
    row = add_dataset(admin)
    assert row['longitudinal'] is None and row['commercial_use'] == 'unknown'
    assert admin.post('/api/catalog', json=dataset_request()).status_code == 409
    update_fields = {k: v for k, v in row.items() if k not in {'id', 'registry', 'external_id', 'last_seen_at', 'dicom_ready', 'dicom_path', 'indexed_patients', 'tumor_detail', 'profile', 'totalseg_status', 'totalseg_detail', 'totalseg_error'}}
    update_fields.update(license_name='Company-reviewed terms', commercial_use='permission_required', status='contacted', longitudinal=False)
    response = admin.put(f'/api/catalog/{row["id"]}', json=update_fields)
    assert response.status_code == 200, response.text
    assert response.json()['version'] == 2
    assert admin.put(f'/api/catalog/{row["id"]}', json=update_fields).status_code == 409
    assert admin.get('/api/catalog?q=Synthetic&modality=CT').json()['total'] == 1
    assert admin.get('/api/catalog?q=%25').json()['total'] == 0


def test_oncoradar_refresh_does_not_overwrite_curation_or_annotations(clients):
    admin, reader, _ = clients
    case = fixture_case()
    study_id = assigned(reader, case)
    completed = complete(reader, study_id)
    row = add_dataset(admin)
    fields = {k: v for k, v in row.items() if k not in {'id', 'registry', 'external_id', 'last_seen_at', 'dicom_ready', 'dicom_path', 'indexed_patients', 'tumor_detail', 'profile', 'totalseg_status', 'totalseg_detail', 'totalseg_error'}}
    fields.update(notes='Curated by data team', status='contacted')
    assert admin.put(f'/api/catalog/{row["id"]}', json=fields).status_code == 200
    incoming = {**dataset_request(), 'name': 'Upstream renamed source', 'longitudinal': False, 'notes': ['Source text']}
    result = admin.post('/api/catalog-import', json={'records': [incoming]})
    assert result.status_code == 200, result.text
    assert result.json() == {'created': 0, 'refreshed': 1, 'patients': 0}
    with SessionLocal() as db:
        assert db.get(CatalogDataset, row['id']).notes == 'Curated by data team'
        assert db.get(CatalogDataset, row['id']).status == 'contacted'
        assert db.get(CatalogDataset, row['id']).source_snapshot['name'] == 'Upstream renamed source'
        assert db.get(AnnotationHead, study_id).revision_id == completed['revision_id']
    assert reader.get(f'/api/lung/studies/{study_id}').json()['annotation_status'] == 'completed'


def test_manifest_refresh_preserves_identity_and_is_atomic(clients):
    admin, _, _ = clients
    dataset = add_dataset(admin)
    record, item = add_cohort(admin, dataset['id'])
    record['visit'] = '6-week follow-up'
    result = admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': True, 'records': [record]})
    assert result.json() == {'created': 0, 'refreshed': 1, 'images_downloaded': False}
    fresh = admin.get(f'/api/catalog/{dataset["id"]}/cohort').json()['items'][0]
    assert fresh['id'] == item['id']
    assert fresh['visit'] == '6-week follow-up'
    result = admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': True, 'records': [
        {**record, 'external_id': 'another-series'}, {**record, 'patient_id': 'WRONG-PATIENT'}]})
    assert result.status_code == 409
    assert admin.get(f'/api/catalog/{dataset["id"]}/cohort').json()['total'] == 1
    assert admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': False, 'records': [record]}).status_code == 422
    assert admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': True, 'records': [record, record]}).status_code == 422


def test_catalog_to_image_import_to_annotation_and_export(clients):
    admin, reader, _ = clients
    dataset = add_dataset(admin)
    record, item = add_cohort(admin, dataset['id'])
    assert admin.post('/api/projects/lung-ct/datasets', json={'dataset_id': dataset['id']}).status_code == 200
    volume = (image_directory(fixture_case()) / 'image.nii.gz').read_bytes()
    data = {'project_id': 'lung-ct', 'patient_id': record['patient_id'], 'deidentified': 'true', 'cohort_item_id': item['id']}
    response = admin.post('/api/import', data=data, files={'files': ('image.nii.gz', volume)})
    assert response.status_code == 201, response.text
    case_id = response.json()['case_ids'][0]
    assert admin.post('/api/import', data=data, files={'files': ('image.nii.gz', volume)}).status_code == 409
    assigned_result = reader.post(f'/api/cases/{case_id}/assign', json={})
    assert assigned_result.status_code == 200, assigned_result.text
    study_id = assigned_result.json()['id']
    assert reader.get(f'/api/lung/studies/{study_id}').status_code == 200
    manifest = admin.get('/api/projects/lung-ct/manifest')
    assert manifest.status_code == 200 and 'attachment' in manifest.headers['content-disposition']
    exported = next(c for c in manifest.json()['cases'] if c['id'] == case_id)
    assert exported['source']['cohort_item_id'] == item['id']
    assert exported['source']['identity_verified_by'].startswith('Uploader supplied')
    assert manifest.json()['schema'] == 'oncometra.project-manifest.v1'
    # The same patient at follow-up remains a separate series, not a duplicate or overwritten case.
    followup = {**record, 'external_id': 'PATIENT-1/FOLLOWUP/CT', 'visit': 'week 6'}
    admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': True, 'records': [followup]})
    followup_item = next(i for i in admin.get(f'/api/catalog/{dataset["id"]}/cohort').json()['items'] if i['external_id'] == followup['external_id'])
    response = admin.post('/api/import', data={**data, 'cohort_item_id': followup_item['id']}, files={'files': ('image.nii.gz', volume)})
    assert response.status_code == 201 and response.json()['case_ids'][0] != case_id
    assert reader.get(f'/api/lung/studies/{study_id}').status_code == 200


def test_catalog_job_recovery_and_non_destructive_failure(clients):
    admin, _, _ = clients
    dataset = add_dataset(admin)
    queued = admin.post('/api/catalog-jobs', json={'registry': 'TCIA'}).json()
    assert admin.post('/api/catalog-jobs', json={'registry': 'TCIA'}).json()['id'] == queued['id']
    with SessionLocal() as db:
        row = db.get(CatalogJob, queued['id'])
        row.status, row.lease_token = 'running', 'abandoned-worker'
        row.lease_until = datetime.utcnow() - timedelta(seconds=1)
        db.commit()
    assert run_once(fetch=lambda _: [dataset_request()])
    result = admin.get('/api/catalog-jobs').json()[0]
    assert result['status'] == 'succeeded' and result['result']['refreshed'] == 1
    assert not run_once(fetch=lambda _: [])
    admin.post('/api/catalog-jobs', json={'registry': 'IDC'})
    def unavailable(_):
        raise RuntimeError('Upstream is unavailable')
    assert run_once(fetch=unavailable)
    assert admin.get('/api/catalog-jobs').json()[0]['status'] == 'failed'
    assert admin.get('/api/catalog').json()['items'][0]['id'] == dataset['id']


def test_stale_worker_cannot_publish_after_lease_is_replaced(clients):
    admin, _, _ = clients
    job = admin.post('/api/catalog-jobs', json={'registry': 'TCIA'}).json()
    def slow_fetch(_):
        with SessionLocal() as db:
            db.execute(update(CatalogJob).where(CatalogJob.id == job['id']).values(lease_token=str(uuid4())))
            db.commit()
        return [dataset_request()]
    run_once(fetch=slow_fetch)
    assert admin.get('/api/catalog').json()['total'] == 0


def test_catalog_constraints_and_import_rollback(clients):
    import pytest
    from sqlalchemy.exc import IntegrityError
    from app.platform_services import upsert_discovery
    admin, _, _ = clients
    with SessionLocal() as db:
        upsert_discovery(db, dataset_request())
        db.rollback()
    assert admin.get('/api/catalog').json()['total'] == 0
    admin.post('/api/catalog-jobs', json={'registry': 'TCIA'})
    with SessionLocal() as db:
        job = db.scalar(select(CatalogJob))
        db.add(CatalogJob(registry='TCIA', requested_by=job.requested_by))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    assert len(admin.get('/api/catalog-jobs').json()) == 1


def test_imported_unverified_flags_are_not_treated_as_positive():
    from app.platform_api import normalize_oncoradar
    row = normalize_oncoradar({**dataset_request(), 'seg': 'false', 'longitudinal': 'false'})
    assert row['segmentations'] is None and row['longitudinal'] is None
    assert normalize_oncoradar({**dataset_request(), 'seg': 42})['segmentations'] is True
    assert normalize_oncoradar({**dataset_request(), 'seg': 0})['segmentations'] is None
    long_tumor = "The ACROBAT challenge and routine breast cancer cases " + ("detail " * 30)
    raw = {**dataset_request(), "tumor": long_tumor}
    raw.pop("tumor_types")
    shortened = normalize_oncoradar(raw)
    assert len(shortened["tumor_types"]) == 1
    assert len(shortened["tumor_types"][0]) == 120
    assert shortened["tumor_types"][0].startswith("The ACROBAT challenge")
    assert normalize_oncoradar({**dataset_request(), "commercial": "Allowed", "license": "CC BY"})["commercial_use"] == "permitted"
    assert normalize_oncoradar({**dataset_request(), "commercial": "Not allowed"})["commercial_use"] == "noncommercial"
    assert normalize_oncoradar({**dataset_request(), "commercial": ""})["commercial_use"] == "unknown"
    assert normalize_oncoradar({**dataset_request(), "registry": "TCIA", "access": "Open · some restricted"})["access"] == "request"
    assert normalize_oncoradar({**dataset_request(), "registry": "IDC", "access": "Open"})["access"] == "direct"
    assert normalize_oncoradar({**dataset_request(), "registry": "TCIA", "access": "Open"})["access"] == "account"


def test_oncoradar_sync_copies_dicom_path_and_patient_index(clients, tmp_path):
    import sqlite3
    admin, _, _ = clients
    database = tmp_path / "oncoradar.sqlite"
    dicom = tmp_path / "dicom"
    with sqlite3.connect(database) as db:
        db.execute("""CREATE TABLE datasets (
            id TEXT, registry TEXT, name TEXT, url TEXT, tumor TEXT, modalities TEXT,
            notes TEXT, access TEXT, longitudinal INT, seg INT, dl_on INT, dl_path TEXT,
            domain TEXT, sub TEXT, hist TEXT, trial TEXT, patients INT, license TEXT,
            commercial TEXT, patients_indexed_at TEXT)""")
        db.execute("""CREATE TABLE dataset_patients (
            dataset_id TEXT, source_id TEXT, study_dates TEXT)""")
        long_tumor = "The ACROBAT challenge and routine breast cancer cases " + ("detail " * 30)
        db.execute(
            """INSERT INTO datasets VALUES (?, 'TCIA', 'NSCLC radiogenomics', 'https://example.org/nsclc', ?, ?, '[]', 'Direct download', 1, 0, 1, ?,
               'Oncology', 'Bronchus and lung', 'Adenocarcinoma', 'ACRIN', 211, 'CC BY 4.0', 'noncommercial', '2026-01-01')""",
            ("NSCLC", long_tumor, json.dumps(["CT"]), str(dicom)),
        )
        db.execute(
            "INSERT INTO dataset_patients VALUES ('NSCLC', 'AMC-001', ?)",
            (json.dumps(["20200101", "20200601"]),),
        )
        db.commit()
    result = admin.post("/api/oncoradar-sync", json={"database": str(database)})
    assert result.status_code == 200, result.text
    assert result.json()["created"] == 1
    assert result.json()["patients"] == 0
    catalog = admin.get("/api/catalog?q=NSCLC").json()["items"][0]
    assert catalog["dicom_ready"] is True
    assert catalog["dicom_path"] == str(dicom)
    assert catalog["indexed_patients"] == 0
    assert catalog["profile"]["domain"] == "Oncology"
    assert catalog["profile"]["sub"] == "Bronchus and lung"
    assert catalog["profile"]["hist"] == "Adenocarcinoma"
    assert catalog["profile"]["trial"] == "ACRIN"
    assert catalog["profile"]["patient_count"] == 211
    assert catalog["profile"]["license"] == "CC BY 4.0"
    assert catalog["profile"]["commercial"] == "noncommercial"
    assert catalog["commercial_use"] == "noncommercial"
    assert catalog["license_name"] == "CC BY 4.0"
    assert catalog["access"] == "direct"
    assert catalog["profile"]["modalities"] == ["CT"]
    assert catalog["profile"]["access"] == "Direct download"
    assert catalog["profile"]["longitudinal"] == 1
    assert catalog["profile"]["seg"] == 0
    assert catalog["profile"]["dl_on"] == 1
    assert "dl_path" not in catalog["profile"]
    assert "patients_indexed_at" not in catalog["profile"]
    assert len(catalog["tumor_types"][0]) == 120
    with SessionLocal() as db:
        assert db.get(CatalogDataset, catalog["id"]).tumor_detail.startswith("The ACROBAT challenge")
        assert len(db.get(CatalogDataset, catalog["id"]).tumor_detail) > 120
    index = admin.get(f"/api/catalog/{catalog['id']}/patient-index").json()
    assert index["total"] == 0
    fields = {k: v for k, v in catalog.items() if k not in {"id", "registry", "external_id", "last_seen_at", "dicom_ready", "dicom_path", "indexed_patients", "tumor_detail", "profile", "totalseg_status", "totalseg_detail", "totalseg_error"}}
    fields.update(notes="Curated by data team", commercial_use="permission_required")
    assert admin.put(f"/api/catalog/{catalog['id']}", json=fields).status_code == 200
    with sqlite3.connect(database) as db:
        db.execute("UPDATE datasets SET hist = 'Squamous' WHERE id = 'NSCLC'")
        db.execute("UPDATE dataset_patients SET study_dates = ? WHERE source_id = 'AMC-001'", (json.dumps(["20210101"]),))
        db.commit()
    again = admin.post("/api/oncoradar-sync", json={"database": str(database)})
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0 and again.json()["patients"] == 0
    kept = admin.get("/api/catalog?q=NSCLC").json()["items"][0]
    assert kept["notes"] == "Curated by data team"
    assert kept["commercial_use"] == "permission_required"
    assert kept["profile"]["hist"] == "Squamous"
    assert admin.get(f"/api/catalog/{kept['id']}/patient-index").json()["total"] == 0
    metadata_only = {**dataset_request(), "registry": "TCIA", "external_id": "NSCLC", "name": "NSCLC radiogenomics", "url": "https://example.org/nsclc"}
    assert admin.post("/api/catalog-import", json={"records": [metadata_only]}).json()["patients"] == 0
    assert admin.get(f"/api/catalog/{kept['id']}/patient-index").json()["total"] == 0
    assert admin.post("/api/oncoradar-sync", json={"database": str(tmp_path / "missing.sqlite")}).status_code == 404


def test_totalseg_stats_records_organs_and_first_lesion(clients, tmp_path):
    admin, _, _ = clients
    dataset = add_dataset(admin)
    assert admin.post(f"/api/catalog/{dataset['id']}/totalseg").status_code == 422
    files = []
    for index in range(8):
        path = tmp_path / f"{index}.dcm"
        path.write_bytes(b"dicom")
        files.append(path)
    with SessionLocal() as db:
        row = db.get(CatalogDataset, dataset["id"])
        row.dicom_path = str(tmp_path)
        row.dicom_ready = True
        row.indexed_patients = 1
        row.tumor_detail = "lung primary"
        db.add(CatalogPatientIndex(dataset_id=row.id, source_id="P1", study_dates=["2020-01-01"]))
        db.commit()
    from app.services.totalseg_stats import SeriesRef, execute
    tree = {"P1": {"2020-01-01": [SeriesRef("P1", "2020-01-01", "1.2.3", "CT", "axial", files)]}}

    def fake(task, series_dir, out_dir):
        if task == "total":
            return {"liver": {"volume": 50000}, "lung_upper_lobe_left": {"volume": 80000}}
        assert task == "lung_nodules"
        return {"lung_nodule": {"volume": 1200}}

    stats = execute(dataset["id"], run_task=fake, series_tree=tree)
    assert stats["ran"] == 1 and stats["errors"] == 0
    result = admin.get(f"/api/catalog/{dataset['id']}/totalseg").json()
    assert result["status"] == "done"
    visit = result["items"][0]["visits"][0]
    assert visit["organs"] == "liver, lung"
    assert visit["lesion"].startswith("LUNG")
    assert "1.2" in visit["lesion"]


def test_dicom_import_checks_manifest_identity_and_preserves_source(clients, tmp_path):
    import io
    import zipfile
    import numpy as np
    import SimpleITK as sitk
    admin, _, _ = clients
    dataset = add_dataset(admin)
    study_uid, series_uid = '1.2.826.0.1.3680043.10.543.1', '1.2.826.0.1.3680043.10.543.2'
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as output:
        for index in range(4):
            image = sitk.GetImageFromArray(np.full((24, 24), index, dtype=np.int16))
            for tag, value in {'0008|0060': 'CT', '0010|0020': 'SYNTHETIC',
                '0020|000d': study_uid, '0020|000e': series_uid, '0020|0013': str(index + 1),
                '0020|0032': f'0\\0\\{index * 2}', '0020|0037': '1\\0\\0\\0\\1\\0',
                '0018|0050': '2', '0008|0018': f'{series_uid}.{index + 1}'}.items():
                image.SetMetaData(tag, value)
            path = tmp_path / f'{index}.dcm'
            writer = sitk.ImageFileWriter()
            writer.KeepOriginalImageUIDOn()
            writer.SetFileName(str(path))
            writer.Execute(image)
            output.write(path, path.name)
    record = {'external_id': 'DICOM-series', 'patient_id': 'SYNTHETIC', 'modality': 'CT',
              'study_uid': study_uid, 'series_uid': series_uid}
    rows = [record, {**record, 'external_id': 'wrong-series', 'series_uid': series_uid + '.999'},
            {**record, 'external_id': 'wrong-study', 'study_uid': study_uid + '.999'}]
    assert admin.post(f'/api/catalog/{dataset["id"]}/cohort', json={'deidentified': True, 'records': rows}).status_code == 200
    admin.post('/api/projects/lung-ct/datasets', json={'dataset_id': dataset['id']})
    items = admin.get(f'/api/catalog/{dataset["id"]}/cohort').json()['items']
    for item in items:
        result = admin.post('/api/import', data={'project_id': 'lung-ct', 'patient_id': 'SYNTHETIC',
            'deidentified': 'true', 'cohort_item_id': item['id']}, files={'files': ('dicom.zip', archive.getvalue())})
        if item['external_id'].startswith('wrong'):
            assert result.status_code == 422 and 'does not match' in result.text
        else:
            assert result.status_code == 201, result.text
            with SessionLocal() as db:
                case = db.get(WorkspaceCase, result.json()['case_ids'][0])
                assert case.source['identity_verified_by'] == 'DICOM manifest UID match'
                assert case.source['series_uid'] == series_uid
                assert (image_directory(case) / 'original-dicom.zip').exists()


def test_eligible_catalog_opens_one_cohort_and_reports_gaps(clients):
    admin, reader, _reviewer = clients
    hidden = add_dataset(admin)
    opened = admin.post('/api/catalog', json=dataset_request(
        external_id='OPEN-COMMERCIAL', name='Open commercial source', commercial_use='permitted', access='direct')).json()
    gated = admin.post('/api/catalog', json=dataset_request(
        external_id='PERMITTED-GATED', name='Permitted but gated', commercial_use='permitted', access='request')).json()
    eligible = [item['id'] for item in admin.get('/api/catalog?scope=eligible').json()['items']]
    assert opened['id'] in eligible
    assert hidden['id'] not in eligible and gated['id'] not in eligible
    stacked = [item['id'] for item in admin.get('/api/catalog?commercial_use=permitted&access=direct&registry=Test').json()['items']]
    assert opened['id'] in stacked and gated['id'] not in stacked and hidden['id'] not in stacked
    assert admin.get('/api/catalog?commercial_use=unknown&masks=unknown&q=Synthetic').json()['total'] >= 1
    assert reader.post(f'/api/catalog/{opened["id"]}/use').status_code == 403
    first = admin.post(f'/api/catalog/{opened["id"]}/use')
    assert first.status_code == 201, first.text
    body = first.json()
    assert body['created'] is True
    assert body['gaps'] == ['images non importées', 'pas de masque']
    second = admin.post(f'/api/catalog/{opened["id"]}/use')
    assert second.status_code == 200
    assert second.json()['created'] is False and second.json()['project_id'] == body['project_id']
    unclear = admin.post(f'/api/catalog/{hidden["id"]}/use')
    assert unclear.status_code == 201
    assert 'licence non tranchée' in unclear.json()['gaps']
    visible = reader.get('/api/workspace').json()['projects']
    cohort = next(item for item in visible if item['id'] == body['project_id'])
    assert cohort['dataset']['commercial_use'] == 'permitted'
    organ = next(item for item in admin.get('/api/workspace').json()['projects'] if item['id'] == 'lung-ct')
    assert 'dataset' not in organ


def test_discovery_keeps_unknown_fields_and_rejects_unexpected_payload(monkeypatch):
    import httpx
    from app import catalog_connectors
    original = httpx.Client
    def client_for(payload):
        return lambda **kwargs: original(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), **kwargs)
    monkeypatch.setattr(catalog_connectors.httpx, 'Client', client_for([{'Collection': 'SOURCE-A'}]))
    record = catalog_connectors.fetch_catalog('TCIA')[0]
    assert record['modalities'] == [] and record['tumor_types'] == []
    assert 'commercial_use' not in record and 'longitudinal' not in record
    monkeypatch.setattr(catalog_connectors.httpx, 'Client', client_for({'unexpected': 'shape'}))
    import pytest
    with pytest.raises(ValueError, match='unsupported'):
        catalog_connectors.fetch_catalog('IDC')
