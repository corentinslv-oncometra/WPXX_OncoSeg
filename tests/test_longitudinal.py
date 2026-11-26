import json
from types import SimpleNamespace

import numpy as np
import pytest
import SimpleITK as sitk

from app.services.lesion_followup import _rank_from_enhancement, followup_lesion_labels, select_followup_cases
from app.services.longitudinal import (
    NumberSwapRequired, _missing_registration, commit_number_change, evolution_rows, lesion_centers,
    native_z_mm, registered_shift, slice_for_registered_z,
)


def test_a_registered_shift_maps_each_date_onto_the_same_z():
    assert native_z_mm(10, origin_z=0, spacing_z=1.5, direction_zz=1) == 15
    centers = [{"lesion_id": 1, "z_mm": 30.0, "registered_z_mm": 12.0}]
    assert registered_shift(centers) == -18
    assert slice_for_registered_z(12, origin_z=0, spacing_z=1.5, direction_zz=1, shift_mm=-18, count=40) == 20
    assert slice_for_registered_z(12, origin_z=0, spacing_z=3, direction_zz=-1, shift_mm=0, count=10) == 0


def test_centers_use_the_middle_axial_slice_and_evolution_uses_the_first_volume():
    labels = np.zeros((12, 4, 4), np.uint16)
    labels[8:12, 1:3, 1:3] = 1
    centers = lesion_centers(labels, origin=(0, 0, 0), spacing=(1, 1, 2), direction=np.eye(3).ravel())
    assert centers[0]["lesion_id"] == 1
    assert centers[0]["axial_index"] == 10
    assert centers[0]["z_mm"] == 19
    rows = evolution_rows([
        {"lesion_id": 1, "time_id": "t0", "status": "nouvelle", "volume_cm3": 2},
        {"lesion_id": 1, "time_id": "t1", "status": "réponse", "volume_cm3": 1},
    ], ["t0", "t1"])
    assert rows[0]["status"] == "réponse"
    assert rows[0]["volumes"] == {"t0": 2, "t1": 1}
    assert rows[0]["delta_percent"] == -50
    own = evolution_rows([
        {"lesion_id": 1, "time_id": "t0", "status": "nouvelle", "volume_cm3": 8.689},
        {"lesion_id": 1, "time_id": "t1", "status": "disparue", "volume_cm3": 0},
        {"lesion_id": 1, "time_id": "t2", "status": "disparue", "volume_cm3": 0},
        {"lesion_id": 2, "time_id": "t1", "status": "nouvelle", "volume_cm3": 80.531},
        {"lesion_id": 2, "time_id": "t2", "status": "stable", "volume_cm3": 103.143},
        {"lesion_id": 3, "time_id": "t2", "status": "nouvelle", "volume_cm3": 0.732},
    ], ["t0", "t1", "t2"])
    assert [row["delta_percent"] for row in own] == [-100.0, 28.1, None]
    assert rows[0]["measures"]["t1"]["status"] == "réponse"
    assert rows[0]["measures"]["t1"]["volume_cm3"] == 1


def _case(path):
    return SimpleNamespace(patient_id="HCC_043", source={"local_timepoint": path})


def test_a_precontrast_series_yields_to_the_contrast_series_of_the_same_day():
    kept, omitted = select_followup_cases([
        _case("HCC_043/2000-12-19-CT/104-LIVER 3 PHASE (AP)-1"),
        _case("HCC_043/2001-01-26-CT/2-PRE LIVER-2"),
        _case("HCC_043/2001-01-26-CT/4-3 PHASE LIVER (ABD)-3"),
    ])
    assert [item.source["local_timepoint"] for item in kept] == [
        "HCC_043/2000-12-19-CT/104-LIVER 3 PHASE (AP)-1",
        "HCC_043/2001-01-26-CT/4-3 PHASE LIVER (ABD)-3",
    ]
    assert omitted == ["2-PRE LIVER-2"]


def test_a_precontrast_series_stays_when_it_is_the_only_series_that_day():
    kept, omitted = select_followup_cases([_case("HCC_043/2001-01-26-CT/2-PRE LIVER-2")])
    assert len(kept) == 1
    assert omitted == []


def test_a_day_keeps_the_portal_phase_and_drops_the_arterial_one():
    kept, omitted = select_followup_cases([
        _case("HCC_001/2000-04-21-CT/1-ARTERIAL-1"),
        _case("HCC_001/2000-04-21-CT/2-PORTAL VENOUS-2"),
    ])
    assert [item.source["local_timepoint"] for item in kept] == [
        "HCC_001/2000-04-21-CT/2-PORTAL VENOUS-2",
    ]
    assert omitted == ["1-ARTERIAL-1"]


def test_unnamed_phases_are_separated_by_vessel_enhancement():
    assert _rank_from_enhancement(378.2, 95.4, 72.3) < _rank_from_enhancement(170.8, 195.4, 109.5)
    assert _rank_from_enhancement(60.1, 34.6, 56.0) < _rank_from_enhancement(378.2, 95.4, 72.3)


def test_two_unnamed_series_of_one_day_collapse_to_a_single_exam():
    kept, omitted = select_followup_cases([
        _case("HCC_001/2000-04-21-CT/100-46705"),
        _case("HCC_001/2000-04-21-CT/101-35194"),
    ])
    assert len(kept) == 1
    assert len(omitted) == 1


def test_the_series_that_carries_the_segmentation_wins_a_tie():
    plain = _case("HCC_001/2000-04-21-CT/2-PORTAL-2")
    indexed = _case("HCC_001/2000-04-21-CT/1-PORTAL-1")
    indexed.source["tumor_from_seg"] = True
    kept, omitted = select_followup_cases([plain, indexed])
    assert kept == [indexed]
    assert omitted == ["2-PORTAL-2"]


def test_lung_cancer_keeps_the_chest_and_a_whole_body_ct_when_that_is_all_there_is():
    paths = [
        "ACRIN/1960-01-10-Thorax/2-Chest 5.0 B30s-88591",
        "ACRIN/1960-01-10-Thorax/3-Abdomen 5.0 B30s-06605",
        "ACRIN/1960-01-10-Thorax/1-Topogram-40919",
        "ACRIN/1960-01-24-Abdomen/2-CT WB 5.0 B30s-39560",
        "ACRIN/1960-01-24-Abdomen/605-PET WB-60546",
        "ACRIN/1960-01-24-Abdomen/606-PET WB-uncorrected-24597",
        "ACRIN/1960-05-31-Abdomen/2-CT WB 5.0 B30s-19975",
        "ACRIN/1960-05-31-Abdomen/605-PET WB-uncorrected-03662",
        "ACRIN/1960-05-31-Abdomen/606-PET WB-54932",
        "ACRIN/1960-08-30-Thorax/2-Chest W 5.0 B30s-15219",
    ]
    kept, omitted = select_followup_cases([_case(path) for path in paths], cancer="NSCLC")
    assert [item.source["local_timepoint"] for item in kept] == [
        paths[0], paths[3], paths[6], paths[9],
    ]
    assert omitted == [
        "1-Topogram-40919",
        "605-PET WB-60546",
        "606-PET WB-uncorrected-24597",
        "605-PET WB-uncorrected-03662",
        "606-PET WB-54932",
        "3-Abdomen 5.0 B30s-06605",
    ]


def test_a_dedicated_chest_outranks_a_whole_body_ct_for_lung_cancer():
    kept, omitted = select_followup_cases([
        _case("P/1960-01-24/9-CT WB 5.0 B30s-1"),
        _case("P/1960-01-24/2-Chest 5.0 B30s-2"),
    ], cancer="lung")
    assert [item.source["local_timepoint"] for item in kept] == ["P/1960-01-24/2-Chest 5.0 B30s-2"]
    assert omitted == ["9-CT WB 5.0 B30s-1"]


def test_liver_cancer_keeps_the_portal_series_and_drops_a_chest():
    kept, omitted = select_followup_cases([
        _case("HCC_001/2000-04-21-CT/4-ABDOMEN-4"),
        _case("HCC_001/2000-04-21-CT/3-CHEST-3"),
        _case("HCC_001/2000-04-21-CT/1-ARTERIAL-1"),
        _case("HCC_001/2000-04-21-CT/2-PORTAL VENOUS-2"),
    ], cancer="HCC")
    assert [item.source["local_timepoint"] for item in kept] == [
        "HCC_001/2000-04-21-CT/2-PORTAL VENOUS-2",
    ]
    assert omitted == ["4-ABDOMEN-4", "3-CHEST-3", "1-ARTERIAL-1"]


def test_a_mask_without_lung_does_not_count_as_covering_the_chest(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.lesion_followup.series_result_dir", lambda uid: tmp_path / uid)
    chest = _case("P/1960-01-10/2-Chest 5.0 B30s-2")
    chest.source["series_instance_uid"] = "chest"
    abdomen = _case("P/1960-01-10/3-Abdomen 5.0 B30s-3")
    abdomen.source["series_instance_uid"] = "abdomen"
    for uid, names in (("chest", ["liver"]), ("abdomen", ["lung_upper_lobe_left"])):
        folder = tmp_path / uid
        folder.mkdir()
        (folder / "hu.json").write_text(
            json.dumps({"organs": [{"name": name} for name in names]}),
            encoding="utf-8",
        )
    kept, omitted = select_followup_cases([chest, abdomen], cancer="NSCLC")
    assert kept == [abdomen]
    assert omitted == ["2-Chest 5.0 B30s-2"]


def test_tracking_without_a_registered_position_must_be_recomputed():
    assert _missing_registration([{"volume_cm3": 6.1}])
    assert not _missing_registration([{"volume_cm3": 6.1, "registered_z_mm": -95.0}])
    assert not _missing_registration([{"volume_cm3": 0.0}])


def _tracking(folder, labels):
    image = sitk.GetImageFromArray(labels)
    image.SetSpacing((1.5, 1.5, 5.0))
    image.SetOrigin((0.0, 0.0, -10.0))
    sitk.WriteImage(image, str(folder / "t0.nii.gz"), True)
    payload = {
        "times": ["t0"],
        "lesions": [
            {"lesion_id": 1, "time_id": "t0", "volume_cm3": 1.0, "parent_ids": [], "child_ids": [2]},
            {"lesion_id": 2, "time_id": "t0", "volume_cm3": 2.0, "parent_ids": [1], "child_ids": [], "event": "division"},
        ],
    }
    (folder / "tracking.json").write_text(__import__("json").dumps(payload), encoding="utf-8")


def test_a_free_number_renames_the_lesion_everywhere(tmp_path):
    labels = np.zeros((2, 2, 2), np.uint16)
    labels[0, :, :] = 1
    labels[1, :, :] = 2
    _tracking(tmp_path, labels)
    assert commit_number_change(tmp_path, 2, 5, swap=False) is False
    stored = __import__("json").loads((tmp_path / "tracking.json").read_text(encoding="utf-8"))
    by_id = {row["lesion_id"]: row for row in stored["lesions"]}
    assert set(by_id) == {1, 5}
    assert by_id[1]["child_ids"] == [5]
    assert by_id[5]["parent_ids"] == [1]
    written = sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / "t0.nii.gz")))
    assert set(np.unique(written)) == {1, 5}
    assert int(written[1, 0, 0]) == 5
    geometry = sitk.ReadImage(str(tmp_path / "t0.nii.gz"))
    assert geometry.GetSpacing()[2] == 5.0


def test_an_occupied_number_is_exchanged_only_after_confirmation(tmp_path):
    labels = np.zeros((2, 2, 2), np.uint16)
    labels[0] = 1
    labels[1] = 2
    _tracking(tmp_path, labels)
    with pytest.raises(NumberSwapRequired, match="Échanger N2 et N1"):
        commit_number_change(tmp_path, 2, 1, swap=False)
    assert commit_number_change(tmp_path, 2, 1, swap=True) is True
    written = sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / "t0.nii.gz")))
    assert int(written[0, 0, 0]) == 2
    assert int(written[1, 0, 0]) == 1
    stored = __import__("json").loads((tmp_path / "tracking.json").read_text(encoding="utf-8"))
    by_id = {row["lesion_id"]: row for row in stored["lesions"]}
    assert by_id[2]["child_ids"] == [1]
    assert by_id[1]["parent_ids"] == [2]
    assert stored["number_changes"] == [{"from": 2, "to": 1, "swapped": True}]


def test_an_unknown_number_is_refused(tmp_path):
    _tracking(tmp_path, np.zeros((1, 1, 1), np.uint16))
    with pytest.raises(Exception, match="n’est pas dans ce suivi"):
        commit_number_change(tmp_path, 9, 4, swap=False)


def test_followup_keeps_the_nodules_and_drops_the_lung(monkeypatch):
    monkeypatch.setattr(
        "app.services.lesion_followup.class_names",
        lambda task: {1: "lung", 2: "lung_nodules"} if task == "lung_nodules" else {1: "liver_lesions"},
    )
    labels = np.array([0, 1, 2], np.int32)
    assert followup_lesion_labels(labels, "Non-small Cell Lung Cancer").tolist() == [0, 0, 1]
    assert followup_lesion_labels(np.array([0, 1], np.int32), "HCC").tolist() == [0, 1]
