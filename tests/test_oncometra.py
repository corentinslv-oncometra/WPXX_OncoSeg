"""Deployment smoke tests, isolated from the user's local annotation database."""

import io
import json
import os
from pathlib import Path
import tempfile
import time
import zipfile
from uuid import uuid4

import numpy as np
import pytest
import SimpleITK as sitk

TEMP = tempfile.TemporaryDirectory(prefix="oncometra-test-")
os.environ["APP_STORAGE_ROOT"] = TEMP.name
os.environ["ONCOMETRA_ADMIN_PASSWORD"] = "test-admin-password-1234"
os.environ.pop("DATABASE_URL", None)

from fastapi.testclient import TestClient
from app.oncometra import app, image_directory, SessionLocal, WorkspaceCase, WorkspaceFeatureJob, lung
from app.db import Base, engine


@pytest.fixture(autouse=True)
def isolated_login_limits():
    from app.oncometra import _login_attempts
    _login_attempts.clear()


@pytest.fixture
def clients():
    Base.metadata.drop_all(engine)
    lung.image_for.cache_clear()
    with TestClient(app) as admin:
        assert admin.post("/api/auth/login", json={"username": "saad", "password": os.environ["ONCOMETRA_ADMIN_PASSWORD"]}).status_code == 200
        for username, role in [("reader", "junior_annotator"), ("reviewer", "reviewer")]:
            assert admin.post("/api/users", json={"username": username, "name": username.title(), "role": role, "password": "test-reader-password-1234"}).status_code == 201
        with TestClient(app, raise_server_exceptions=True) as reader, TestClient(app) as reviewer:
            for client, username in ((reader,"reader"),(reviewer,"reviewer")):
                assert client.post("/api/auth/login", json={"username":username,"password":"test-reader-password-1234"}).status_code == 200
            yield admin, reader, reviewer


def fixture_case(modality="CT"):
    # Synthetic volumes are test fixtures only, never demo assets.
    array = np.arange(24**3, dtype=np.float32).reshape(24,24,24) / 17.3 - 400
    image = sitk.GetImageFromArray(array)
    image.SetSpacing((1.1,1.2,1.3))
    mask = sitk.GetImageFromArray(np.pad(np.ones((8,8,8),np.uint8),8))
    mask.CopyInformation(image)
    case = WorkspaceCase(id=str(uuid4()), project_id="brain-mr" if modality=="MR" else "lung-ct", patient_id="TEST-"+str(uuid4())[:8], modality=modality,
                         source={"source":"Synthetic unit-test fixture", "reference_voxels":512})
    directory = image_directory(case)
    directory.mkdir(parents=True)
    sitk.WriteImage(image,str(directory/"image.nii.gz"))
    sitk.WriteImage(mask,str(directory/"reference.nii.gz"))
    with SessionLocal() as db:
        db.add(case)
        db.commit()
    return case


def assigned(client, case):
    result=client.post(f"/api/cases/{case.id}/assign",json={})
    assert result.status_code==200,result.text
    return result.json()["id"]


def complete(client, study_id):
    base=f"/api/lung/studies/{study_id}"
    state=client.get(base).json()
    result=client.post(f"/api/assignments/{study_id}/reference",json={"version":state["version"]})
    assert result.status_code==200,result.text
    state=client.get(base).json()
    result=client.post(base+"/complete",json={"version":state["version"],"revision_id":state["revision_id"],"reviewed":True})
    assert result.status_code==200,result.text
    return client.get(base).json()


def test_seeded_demo_volumes_are_removed_from_the_workspace(clients):
    admin, _, _ = clients
    info = json.loads((Path(__file__).resolve().parents[1] / "demo-cases" / "lung-ct" / "case.json").read_text())
    kept = fixture_case()
    case = WorkspaceCase(id=str(uuid4()), project_id=info["project_id"], patient_id=info["patient_id"],
                         modality=info["modality"], source=info)
    directory = image_directory(case)
    directory.mkdir(parents=True)
    (directory / "image.nii.gz").write_bytes(b"demo-placeholder")
    with SessionLocal() as db:
        db.add(case)
        db.commit()
    assigned(admin, case)
    from app.oncometra import seed_demo
    seed_demo()
    workspace = admin.get("/api/workspace").json()
    assert [item["patient_id"] for item in workspace["cases"]] == [kept.patient_id]
    assert not directory.exists()
    with SessionLocal() as db:
        assert db.get(WorkspaceCase, case.id) is None


def test_authentication_and_csrf(clients):
    admin, reader, reviewer=clients
    with TestClient(app) as anonymous:
        assert anonymous.get('/api/workspace').status_code==401
        assert anonymous.get('/api/lung/identities',headers={'X-Annotation-Actor':'reviewer'}).status_code==401
        assert anonymous.get('/healthz').status_code==200
    assert reader.post('/api/users',json={'username':'hacker','name':'Unauthorized','role':'admin','password':'test-invalid-account'}).status_code==403
    assert admin.post('/api/auth/logout',json={},headers={'Origin':'https://untrusted.example'}).status_code==403
    assert reader.get('/api/lung/identities',headers={'X-Annotation-Actor':'reviewer'}).json()['current']['role']=='junior_annotator'


@pytest.mark.parametrize('role', ['junior_annotator', 'admin'])
def test_bootstrap_account_survives_restart_without_resetting_existing_user(monkeypatch, role):
    from app.oncometra import password_hash

    Base.metadata.drop_all(engine)
    entry = {'username': 'laurent', 'name': 'Laurent', 'role': role,
             'password_hash': password_hash('test-laurent-password-1234')}
    monkeypatch.setenv('ONCOMETRA_BOOTSTRAP_USERS', json.dumps([entry]))
    with TestClient(app) as client:
        result = client.post('/api/auth/login', json={'username': 'laurent', 'password': 'test-laurent-password-1234'})
        assert result.status_code == 200
        assert result.json()['role'] == role
        assert client.get('/api/users').status_code == (200 if role == 'admin' else 403)
    entry.update(role='reviewer', password_hash=password_hash('different-bootstrap-password'))
    monkeypatch.setenv('ONCOMETRA_BOOTSTRAP_USERS', json.dumps([entry]))
    with TestClient(app) as client:
        result = client.post('/api/auth/login', json={'username': 'laurent', 'password': 'test-laurent-password-1234'})
        assert result.status_code == 200
        assert result.json()['role'] == role
        assert client.post('/api/auth/login', json={'username': 'laurent', 'password': 'different-bootstrap-password'}).status_code == 401


def test_role_changes_require_admin_and_preserve_account(clients):
    admin, reader, reviewer = clients
    target = reader.get('/api/auth/me').json()
    study_id = assigned(reader, fixture_case())
    url = f'/api/users/{target["id"]}/role'
    request = {'expected_role': 'junior_annotator', 'role': 'admin'}
    assert reader.patch(url, json=request).status_code == 403
    assert reviewer.patch(url, json=request).status_code == 403
    assert admin.patch(url, json={**request, 'role': 'invalid'}).status_code == 422
    assert admin.patch(url, json=request, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert admin.patch(url, json={**request, 'expected_role': 'reviewer'}).status_code == 409
    promoted = admin.patch(url, json=request)
    assert promoted.status_code == 200, promoted.text
    assert promoted.json() == {**target, 'role': 'admin'}
    assert reader.get('/api/auth/me').status_code == 401
    assert reader.post('/api/auth/login', json={'username':'reader','password':'test-reader-password-1234'}).status_code == 200
    assert reader.get('/api/auth/me').json()['role'] == 'admin'
    assert reader.get(f'/api/lung/studies/{study_id}').status_code == 200
    events = reader.get('/api/audit').json()
    assert any(event['action'] == 'user_role_changed' and event['subject_id'] == target['id']
               and event['details'] == {'from':'junior_annotator','to':'admin'} for event in events)
    owner = admin.get('/api/auth/me').json()
    assert admin.patch(f'/api/users/{owner["id"]}/role', json={'expected_role':'admin','role':'reviewer'}).status_code == 409
    assert admin.patch(f'/api/users/{uuid4()}/role', json=request).status_code == 404
    assert admin.patch(url, json={'expected_role':'admin','role':'junior_annotator'}).status_code == 200
    assert reader.get('/api/auth/me').status_code == 401
    assert reader.post('/api/auth/login', json={'username':'reader','password':'test-reader-password-1234'}).status_code == 200
    assert reader.get('/api/audit').status_code == 403


def test_reader_isolation_and_independent_approval(clients):
    admin, reader, reviewer=clients
    case=fixture_case()
    mine=assigned(reader,case)
    other=assigned(reviewer,case)
    assert mine!=other
    assert reader.get(f'/api/lung/studies/{other}/mask').status_code==403
    assert reader.get(f'/api/lung/studies/{other}/volume').status_code==403
    state=complete(reader,mine)
    assert reviewer.get(f'/api/lung/studies/{other}').json()['revision_id'] is None
    request={'version':state['version'],'revision_id':state['revision_id'],'reviewed':True}
    assert reader.post(f'/api/lung/studies/{mine}/approve',json=request).status_code==403
    assert reviewer.post(f'/api/lung/studies/{mine}/approve',json=request).status_code==200
    assert reader.post(f'/api/lung/studies/{mine}/strokes',json={'version':state['version'],'plane':'axial','slice_index':10,'points':[[10,10]],'radius_mm':2}).status_code==409
    approved=reviewer.get(f'/api/lung/studies/{mine}').json()
    returned=reviewer.post(f'/api/assignments/{mine}/return',json={'version':approved['version'],'comment':'Review the superior boundary'})
    assert returned.status_code==200
    assert reader.get(f'/api/lung/studies/{mine}').json()['annotation_status']=='in_progress'
    own=complete(reviewer,other)
    assert reviewer.post(f'/api/lung/studies/{other}/approve',json={'version':own['version'],'revision_id':own['revision_id'],'reviewed':True}).status_code==403


def test_add_lesion_then_delete_it_keeps_the_connection(clients):
    _, reader, _ = clients
    study_id = assigned(reader, fixture_case())
    base = f"/api/lung/studies/{study_id}"
    state = reader.get(base).json()
    added = reader.post(f"{base}/nodules", json={"version": state["version"]})
    assert added.status_code == 200, added.text
    added_body = added.json()
    assert added_body["nodule_label"] == 2
    assert [nodule["label"] for nodule in added_body["nodules"]] == [1, 2]
    deleted = reader.post(f"{base}/delete-mask", json={"version": added_body["version"], "nodule_label": 2})
    assert deleted.status_code == 200, deleted.text
    assert [nodule["label"] for nodule in deleted.json()["nodules"]] == [1]
    state = reader.get(base)
    assert state.status_code == 200, state.text
    last = reader.post(f"{base}/delete-mask", json={"version": state.json()["version"], "nodule_label": 1})
    assert last.status_code == 200, last.text
    assert last.json()["nodules"] == []
    state = reader.get(base)
    assert state.status_code == 200, state.text
    assert state.json()["nodules"] == []
    mask = reader.get(f"{base}/mask", params={"revision_id": state.json()["revision_id"]})
    assert mask.status_code == 200, mask.text
    assert mask.content


def test_float_mri_and_export_provenance(clients):
    admin, reader, reviewer=clients
    case=fixture_case('MR')
    study_id=assigned(reader,case)
    base=f'/api/lung/studies/{study_id}'
    state=reader.get(base).json()
    assert state['modality']=='MR' and state['transfer_dtype']=='float32-le'
    pixels=np.frombuffer(reader.get(base+'/volume').content,dtype='<f4')
    assert pixels[1]==pytest.approx(1/17.3-400)
    state=complete(reader,study_id)
    result=reader.get(base+f"/exports/{state['revision_id']}",params={'version':state['version'],'format':'bundle'})
    assert result.status_code==200,result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert 'image.nii.gz' in archive.namelist()
        manifest=json.loads(archive.read('manifest.json'))
        assert manifest['identity_mode']=='authenticated'
        assert manifest['modality']=='MR'
        assert manifest['revision']['details']['practice_only'] is True
        assert manifest['review']['actor']['username']=='reader'


def test_adjudication_preserves_source_and_comparison(clients):
    admin, reader, reviewer=clients
    case=fixture_case()
    original=assigned(reader,case)
    first=complete(reader,original)
    copy=reviewer.post(f'/api/assignments/{original}/adjudicate',json={})
    assert copy.status_code==200,copy.text
    assert copy.json()['kind']=='adjudication'
    assert copy.json()['id']!=original
    assert reader.get(f'/api/lung/studies/{original}').json()['revision_id']==first['revision_id']
    assert reader.get(f"/api/lung/studies/{copy.json()['id']}/mask").status_code==403
    another=assigned(reviewer,case)
    complete(reviewer,another)
    compared=reviewer.post('/api/review/compare',json={'a':original,'b':another})
    assert compared.status_code==200,compared.text
    assert compared.json()['dice']==1


def test_pyradiomics_is_real_versioned_and_invalidated(clients):
    radiomics = pytest.importorskip("radiomics")
    admin, reader, reviewer=clients
    study_id=assigned(reader,fixture_case())
    completed=complete(reader,study_id)
    request={'version':completed['version'],'revision_id':completed['revision_id']}
    assert reader.post(f'/api/assignments/{study_id}/radiomics',json=request).status_code==409
    assert reviewer.post(f'/api/lung/studies/{study_id}/approve',json={**request,'reviewed':True}).status_code==200
    approved=reader.get(f'/api/lung/studies/{study_id}').json()
    request={'version':approved['version'],'revision_id':approved['revision_id']}
    result=reader.post(f'/api/assignments/{study_id}/radiomics',json=request)
    assert result.status_code==202,result.text
    job_id=result.json()['id']
    for _ in range(200):
        jobs=reader.get('/api/radiomics').json()
        job=next(row for row in jobs if row['id']==job_id)
        if job['status'] in ('succeeded','failed'):
            break
        time.sleep(.05)
    assert job['status']=='succeeded',job
    assert job['result']['pyradiomics_version']==radiomics.__version__
    assert len(job['result']['rows'][0]['features'])>90
    assert 'original_shape_MeshVolume' in job['result']['rows'][0]['features']
    assert not job['stale']
    csv_export=reader.get(f'/api/radiomics/{job_id}/export')
    assert csv_export.status_code==200 and 'original_shape_MeshVolume' in csv_export.text
    package=reader.get(f'/api/radiomics/{job_id}/export?format=zip')
    assert package.status_code==200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        protocol=json.loads(archive.read('pyradiomics-settings.json'))
        manifest=json.loads(archive.read('manifest.json'))
        assert protocol['setting']['binWidth']==25
        assert manifest['protocol']['reviewer']['username']=='reviewer'
    assert reviewer.post(f'/api/lung/studies/{study_id}/undo-approval',json={'version':approved['version']}).status_code==200
    assert reader.get('/api/radiomics').json()[0]['stale']
    assert reader.get(f'/api/radiomics/{job_id}/export').status_code==409


def test_configurable_features_require_current_approval(clients):
    admin, reader, reviewer=clients
    study_id=assigned(reader,fixture_case('MR'))
    completed=complete(reader,study_id)
    request={'version':completed['version'],'revision_id':completed['revision_id'],'reviewed':True}
    assert reviewer.post(f'/api/lung/studies/{study_id}/approve',json=request).status_code==200
    approved=reader.get(f'/api/lung/studies/{study_id}').json()
    request={'version':approved['version'],'revision_id':approved['revision_id'],
             'settings':{'families':['shape','firstorder'],'bin_width':10,'normalize':True,'normalize_scale':100}}
    assert reader.post(f'/api/assignments/{study_id}/radiomics',json={**request,'version':0}).status_code==409
    assert reader.post(f'/api/assignments/{study_id}/radiomics',json={**request,'settings':{'families':['madeup']}}).status_code==422
    result=reader.post(f'/api/assignments/{study_id}/radiomics',json=request)
    assert result.status_code==202,result.text
    for _ in range(200):
        job=reader.get('/api/radiomics',params={'study_id':study_id}).json()[0]
        if job['status'] in ('succeeded','failed'):
            break
        time.sleep(.05)
    assert job['status']=='succeeded',job
    assert set(job['protocol']['featureClass'])=={'shape','firstorder'}
    assert all(key.startswith(('original_shape_','original_firstorder_')) for key in job['result']['rows'][0]['features'])


def _write_ct_series(directory: Path, patient_id: str, series_uid: str):
    directory.mkdir(parents=True)
    volume = sitk.GetImageFromArray(np.zeros((4, 8, 8), np.int16))
    volume.SetSpacing((1.0, 1.0, 1.0))
    tags = {"0008|0060": "CT", "0010|0020": patient_id, "0020|000e": series_uid,
            "0020|000d": "1.2.840.10008.1", "0020|0011": "1", "0020|0037": "1\\0\\0\\0\\1\\0"}
    for index in range(volume.GetSize()[2]):
        sl = volume[:, :, index]
        for key, value in tags.items():
            sl.SetMetaData(key, value)
        sl.SetMetaData("0020|0013", str(index + 1))
        sl.SetMetaData("0020|0032", "\\".join(map(str, volume.TransformIndexToPhysicalPoint((0, 0, index)))))
        writer = sitk.ImageFileWriter()
        writer.KeepOriginalImageUIDOn()
        writer.SetFileName(str(directory / f"{index:03d}.dcm"))
        writer.Execute(sl)


def test_cancer_type_selects_lesion_task_and_organ_hu():
    from app.services.exam_autoseg import binary_labels, hu_rows, lesion_task_for_cancer
    liver = lesion_task_for_cancer("Hepatocellular carcinoma (HCC)")
    lung = lesion_task_for_cancer("NSCLC")
    assert liver[0] == "liver_lesions" and lung[0] == "lung_nodules"
    assert lesion_task_for_cancer("Renal cell carcinoma") is None
    ct = np.arange(16, dtype=np.float32).reshape(2, 2, 4)
    labels = np.zeros((2, 2, 4), np.uint8)
    labels[0] = 1
    rows = hu_rows(ct, labels, {1: "liver"}, 1.0)
    assert rows[0]["voxels"] == 8 and rows[0]["hu_min"] == 0 and rows[0]["hu_max"] == 7
    from app.services.exam_autoseg import organ_color
    assert organ_color(1) != organ_color(2) and organ_color(5) == organ_color(5)
    assert all(0 <= channel <= 255 for channel in organ_color(12))
    mask = binary_labels(np.array([[[1, 2]]], np.uint8), {1: "liver_lesions", 2: "liver_vessels"}, ("lesion", "tumor"))
    assert int(mask.sum()) == 1 and mask[0, 0, 0] == 1 and mask[0, 0, 1] == 0


def test_study_seg_file_is_detected_without_reading_pixels(tmp_path):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    from app.services.dicom_seg import study_has_seg

    def write(path, modality, label=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        dataset = Dataset()
        dataset.file_meta = meta
        dataset.is_little_endian = True
        dataset.is_implicit_VR = False
        dataset.Modality = modality
        dataset.SeriesInstanceUID = generate_uid()
        dataset.SOPClassUID = meta.MediaStorageSOPClassUID
        dataset.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        if label:
            segment = Dataset()
            segment.SegmentNumber = 1
            segment.SegmentLabel = label
            dataset.SegmentSequence = [segment]
        dataset.save_as(path, enforce_file_format=True)

    study = tmp_path / "study"
    write(study / "ct" / "one.dcm", "CT")
    assert not study_has_seg(study / "ct")
    write(study / "seg" / "one.dcm", "SEG", "Mass")
    assert study_has_seg(study / "ct")


def test_tumor_segment_is_painted_in_ct_coordinates():
    from app.services.dicom_seg import is_tumor_text, paint_frames, paint_on_grid
    image = sitk.GetImageFromArray(np.zeros((4, 8, 8), np.int16))
    image.SetSpacing((1, 1, 1))
    image.SetOrigin((0, 0, 0))
    frame = np.zeros((8, 8), np.uint8)
    frame[3, 2] = 1
    mask = paint_frames(image, [frame], [[0, 0, 1]], [1, 0, 0], [0, 1, 0], 1, 1)
    assert mask[1, 3, 2] == 1 and int(mask.sum()) == 1
    decreasing = [[0, 0, 10], [0, 0, 8], [0, 0, 6], [0, 0, 4]]
    matched = paint_on_grid(decreasing, [frame], [[0, 0, 6]], [1, 0, 0, 0, 1, 0], 1, 1, 8, 8)
    assert matched[2, 3, 2] == 1 and int(matched.sum()) == 1
    missed = paint_on_grid(decreasing, [frame], [[0, 0, 100]], [1, 0, 0, 0, 1, 0], 1, 1, 8, 8)
    assert int(missed.sum()) == 0
    assert is_tumor_text("Mass", "Tumor")
    assert not is_tumor_text("Liver", "Liver")
    assert not is_tumor_text("Portal vein", "vessels")


def test_local_catalog_opens_one_timepoint(clients):
    admin, _, _ = clients
    root = Path(os.environ["APP_STORAGE_ROOT"]) / "incoming"
    _write_ct_series(root / "PAT1" / "2016-01-02-NA-aaa-11111" / "2-Portal-aaaa1", "P1", "1.2.3.4.5.1")
    _write_ct_series(root / "PAT1" / "2016-06-01-NA-bbb-22222" / "3-Follow-bbbb2", "P1", "1.2.3.4.5.2")
    seg = root / "PAT1" / "2016-01-02-NA-aaa-11111" / "300-SEG-cccc3"
    seg.mkdir(parents=True)
    (seg / "one.dcm").write_bytes(b"0")
    _write_ct_series(root / "PAT2" / "2017-01-01-NA-ddd-44444" / "2-Portal-dddd4", "P2", "1.2.3.4.5.4")
    catalog = admin.get("/api/projects/lung-ct/local-catalog", params={"path": "incoming"})
    assert catalog.status_code == 200, catalog.text
    patients = catalog.json()["patients"]
    assert [item["id"] for item in patients] == ["PAT1", "PAT2"]
    assert len(patients[0]["timepoints"]) == 2
    assert "SEG" not in patients[0]["timepoints"][0]["label"]
    opened = admin.post("/api/projects/lung-ct/local-catalog/open", json={
        "path": "incoming", "patient_id": "PAT1", "timepoint_id": patients[0]["timepoints"][0]["id"]})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["patient_count"] == 2 and body["timepoint_count"] == 2
    assert body["next_patient"]["patient_id"] == "PAT2"
    assert body["next_timepoint"]["patient_id"] == "PAT1"
    again = admin.post("/api/projects/lung-ct/local-catalog/open", json={
        "path": "incoming", "patient_id": "PAT1", "timepoint_id": patients[0]["timepoints"][0]["id"]})
    assert again.status_code == 200, again.text
    assert again.json()["study_id"] == body["study_id"]


def _write_seg_header(directory: Path):
    import pydicom
    from pydicom.dataset import FileDataset, FileMetaDataset
    directory.mkdir(parents=True, exist_ok=True)
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.66.4"
    file_meta.MediaStorageSOPInstanceUID = "1.2.3.4.9.1"
    file_meta.TransferSyntaxUID = pydicom.uid.ExplicitVRLittleEndian
    dataset = FileDataset(str(directory / "seg.dcm"), {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.Modality = "SEG"
    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
    dataset.is_little_endian = True
    dataset.is_implicit_VR = False
    dataset.save_as(directory / "seg.dcm")


def test_patient_list_reports_whether_the_seg_is_present_and_used(clients):
    admin, _, _ = clients
    root = Path(os.environ["APP_STORAGE_ROOT"]) / "nav-set"
    _write_ct_series(root / "PAT1" / "2016-01-02-NA-aaa-11111" / "2-Portal-aaaa1", "P1", "1.2.3.4.8.1")
    _write_seg_header(root / "PAT1" / "2016-01-02-NA-aaa-11111" / "300-SEG-cccc3")
    _write_ct_series(root / "PAT1" / "2016-06-01-NA-bbb-22222" / "3-Follow-bbbb2", "P1", "1.2.3.4.8.2")
    listed = admin.get("/api/projects/lung-ct/local-catalog/patient", params={"path": "nav-set", "patient_id": "PAT1"})
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert rows[0]["seg_present"] is True and rows[0]["seg_used"] is False
    assert rows[1]["seg_present"] is False and rows[1]["seg_used"] is False
    with SessionLocal() as db:
        db.add(WorkspaceCase(
            id=str(uuid4()), project_id="lung-ct", patient_id="PAT1 · portal", modality="CT",
            source={"local_path": "nav-set", "local_timepoint": rows[0]["id"], "seg_present": True, "seg_used": True, "tumor_from_seg": True},
        ))
        db.commit()
    again = admin.get("/api/projects/lung-ct/local-catalog/patient", params={"path": "nav-set", "patient_id": "PAT1"})
    assert again.json()[0]["seg_used"] is True
    assert admin.get("/api/projects/lung-ct/local-catalog/patient", params={"path": "nav-set", "patient_id": "ABSENT"}).status_code == 422


def test_local_folder_import_reads_dicom_inside_data(clients):
    admin, _, _ = clients
    root = Path(os.environ["APP_STORAGE_ROOT"])
    _write_ct_series(root / "incoming" / "series", "LOCAL-1", "1.2.3.4.5.6")
    assert admin.post("/api/projects/lung-ct/import-folder", json={"path": "../outside", "deidentified": True}).status_code == 422
    assert admin.post("/api/projects/lung-ct/import-folder", json={"path": "incoming", "deidentified": False}).status_code == 422
    started = admin.post("/api/projects/lung-ct/import-folder", json={"path": "incoming", "deidentified": True})
    assert started.status_code == 202, started.text
    status = {}
    for _ in range(100):
        status = admin.get("/api/projects/lung-ct/import-folder").json()
        if status["state"] != "running":
            break
        time.sleep(0.05)
    assert status["state"] == "done", status
    assert status["imported"] == 1
    again = admin.post("/api/projects/lung-ct/import-folder", json={"path": "incoming", "deidentified": True})
    assert again.status_code == 202
    for _ in range(100):
        status = admin.get("/api/projects/lung-ct/import-folder").json()
        if status["state"] != "running":
            break
        time.sleep(0.05)
    assert status["imported"] == 0, status


def test_import_limits_and_valid_mri(clients):
    admin, reader, reviewer=clients
    case=fixture_case('MR')
    payload=(image_directory(case)/'image.nii.gz').read_bytes()
    result=reader.post('/api/import',data={'project_id':'brain-mr','patient_id':'UPLOADED-MR','deidentified':'true'},files={'files':('image.nii.gz',payload)})
    assert result.status_code==201,result.text
    assert reader.post('/api/import',data={'project_id':'brain-mr','patient_id':'UPLOADED-MR','deidentified':'false'},files={'files':('image.nii.gz',payload)}).status_code==422
    result=reader.post('/api/import',data={'project_id':'brain-mr','patient_id':'UPLOADED-MR','deidentified':'true'},files={'files':('image.nii.gz',payload)})
    assert result.status_code==422


def test_one_exam_detection_publishes_distinct_organ_colors(clients, monkeypatch):
    import gzip
    from app.services import exam_autoseg
    admin, _, _ = clients
    case = fixture_case()
    study = assigned(admin, case)
    calls = []

    def runner(task, source, output, *, fast):
        calls.append((task, fast))
        image = sitk.ReadImage(str(source))
        labels = np.zeros(tuple(reversed(image.GetSize())), np.uint16)
        labels[0, 0, :16] = 1
        labels[0, 1, :16] = 2
        painted = sitk.GetImageFromArray(labels)
        painted.CopyInformation(image)
        sitk.WriteImage(painted, str(output), True)

    monkeypatch.setattr(exam_autoseg, "class_names", lambda task: {1: "liver", 2: "spleen"} if task == "total" else {1: "lung_nodule"})
    result = exam_autoseg.execute_case(case.id, study, runner=runner, report=lambda *_args, **_fields: None)
    assert calls == [("total", True), ("lung_nodules", False)]
    assert result["detail"].startswith("2 organes colorés")
    overlay = admin.get(f"/api/studies/{study}/organ-overlay")
    assert overlay.status_code == 200, overlay.text
    legend = overlay.json()["legend"]
    assert [item["label"] for item in legend] == ["liver", "spleen", "Lésion"]
    assert legend[0]["color"] != legend[1]["color"]
    assert legend[2]["color"] == [220, 0, 0]
    voxels = admin.get(f"/api/studies/{study}/organ-overlay/voxels")
    assert voxels.status_code == 200
    payload = voxels.content
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    labels = np.frombuffer(payload, dtype="<u2")
    assert labels.size == 24 ** 3 and int(labels[0]) == 65000 and int(labels[24]) == 2
    exam_autoseg._active_case = "busy"
    exam_autoseg._status["busy"] = {"state": "running", "detail": "", "error": "", "seeded": False}
    try:
        refused = admin.post(f"/api/studies/{study}/autoseg")
        assert refused.status_code == 409
    finally:
        exam_autoseg._active_case = None
        exam_autoseg._status.pop("busy", None)


def test_detection_keeps_seg_and_still_runs_the_lesion_task(clients, monkeypatch):
    from app.services import exam_autoseg
    admin, _, _ = clients
    case = fixture_case()
    study = assigned(admin, case)
    reference = image_directory(case) / "reference.nii.gz"
    before = reference.read_bytes()
    with SessionLocal() as db:
        row = db.get(WorkspaceCase, case.id)
        source = dict(row.source or {})
        source["seg_used"] = True
        source["tumor_from_seg"] = True
        row.source = source
        db.commit()
    calls = []

    def runner(task, source_path, output, *, fast):
        calls.append((task, fast))
        image = sitk.ReadImage(str(source_path))
        labels = np.zeros(tuple(reversed(image.GetSize())), np.uint16)
        labels[0, 0, 0] = 1
        painted = sitk.GetImageFromArray(labels)
        painted.CopyInformation(image)
        sitk.WriteImage(painted, str(output), True)

    monkeypatch.setattr(exam_autoseg, "class_names", lambda task: {1: "liver"} if task == "total" else {1: "lung_nodule"})
    result = exam_autoseg.execute_case(case.id, study, runner=runner, report=lambda *_args, **_fields: None)
    assert calls == [("total", True), ("lung_nodules", False)]
    assert result["seeded"] is True
    assert "AI lesion detection" in result["detail"]
    assert "SEG est conservé" in result["detail"]
    assert reference.read_bytes() == before
    from app.models import AnnotationHead, AnnotationRevision
    with SessionLocal() as db:
        head = db.get(AnnotationHead, study)
        saved = db.get(AnnotationRevision, head.revision_id)
    assert [item["name"] for item in saved.details["nodules"]] == ["AI lesion detection"]
    legend = admin.get(f"/api/studies/{study}/organ-overlay").json()
    assert legend["legend"][-1]["id"] == 65000
    assert isinstance(legend["dice"], float)
    assert 0 <= legend["dice"] <= 1
    with SessionLocal() as db:
        source = db.get(WorkspaceCase, case.id).source
    assert source["tumor_from_seg"] is True
    assert source.get("tumor_from_model") is not True
    assert result["dice"] is not None
    assert 0 <= result["dice"] <= 1
    assert "Score Dice" in result["detail"]


def test_kaggle_device_fetches_both_masks_and_skips_the_local_binary(clients, monkeypatch):
    from app.services import exam_autoseg
    admin, _, _ = clients
    case = fixture_case()
    study = assigned(admin, case)
    monkeypatch.setenv("ONCOMETRA_TOTALSEG_DEVICE", "kaggle")
    seen = []

    def remote(image_path, uid, lesion_task, dest, report=None):
        seen.append(lesion_task)
        image = sitk.ReadImage(str(image_path))
        labels = np.zeros(tuple(reversed(image.GetSize())), np.uint16)
        labels[0, 0, :16] = 1
        labels[0, 1, :16] = 2
        painted = sitk.GetImageFromArray(labels)
        painted.CopyInformation(image)
        sitk.WriteImage(painted, str(dest / "organs.nii.gz"), True)
        sitk.WriteImage(painted, str(dest / "lesions.nii.gz"), True)

    def runner(*_args, **_kwargs):
        raise AssertionError("local TotalSegmentator")

    monkeypatch.setattr("app.services.kaggle_autoseg.ensure_remote_masks", remote)
    monkeypatch.setattr(exam_autoseg, "class_names", lambda task: {1: "liver", 2: "spleen"} if task == "total" else {1: "lung_nodule"})
    result = exam_autoseg.execute_case(case.id, study, runner=runner, report=lambda *_args, **_fields: None)
    assert seen == ["lung_nodules"]
    assert "Lésions proposées par lung_nodules" in result["detail"]
    assert "AI lesion detection" in result["detail"]


def test_ai_segmentation_is_reserved_for_an_administrator(clients, monkeypatch):
    admin, reader, _reviewer = clients
    seen = {}

    def fake(project_id, user_id):
        seen["project"] = project_id
        seen["user"] = user_id
        return {"state": "running", "detail": "Lecture des examens…", "error": "", "total": 0, "done": 0, "skipped": 0, "failed": 0, "current": []}

    monkeypatch.setattr("app.services.cohort_autoseg.start_cohort", fake)
    assert reader.post("/api/projects/liver-ct/ai-segmentation").status_code == 403
    started = admin.post("/api/projects/liver-ct/ai-segmentation")
    assert started.status_code == 202
    assert started.json()["state"] == "running"
    assert seen["project"] == "liver-ct"
    assert admin.get("/api/projects/liver-ct/ai-segmentation").status_code == 200


def test_dice_score_measures_overlap_with_the_reference_segment():
    from app.services.exam_autoseg import dice_score
    predicted = np.zeros((2, 2), dtype=bool)
    reference = np.zeros((2, 2), dtype=bool)
    predicted[0, :] = True
    reference[:, 0] = True
    assert dice_score(predicted, reference) == 0.5
    assert dice_score(predicted, np.zeros((3, 3), dtype=bool)) is None
    assert dice_score(np.zeros((2, 2), dtype=bool), np.zeros((2, 2), dtype=bool)) is None
    from app.services import exam_autoseg
    assert exam_autoseg.output_percent("\x1b[32m 42%|██ | 8/20") == 42
    assert exam_autoseg.output_percent("rien") is None
    assert exam_autoseg.span_percent(4, 46, 50) == 25
    assert exam_autoseg.remote_percent("GPU Kaggle : RUNNING") == 62
    case_id = "progress-case"
    exam_autoseg._status.pop(case_id, None)
    started = time.time() - 30
    exam_autoseg._set_status(case_id, state="running", detail="Segmentation des organes…", percent=10, started_at=started, error="", seeded=False)
    exam_autoseg._set_status(case_id, state="running", percent=4, detail="plus tard")
    assert exam_autoseg.detection_status(case_id)["percent"] == 10
    exam_autoseg._set_status(case_id, state="done", detail="fini", seeded=False)
    exam_autoseg._status[case_id]["finished_at"] = started + 12
    assert exam_autoseg.detection_status(case_id)["elapsed_s"] == 12
    assert exam_autoseg.detection_status(case_id)["percent"] == 100
    exam_autoseg._status.pop(case_id, None)
