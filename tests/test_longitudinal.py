from types import SimpleNamespace

import numpy as np

from app.services.lesion_followup import select_followup_cases
from app.services.longitudinal import (
    _missing_registration, evolution_rows, lesion_centers, native_z_mm, registered_shift, slice_for_registered_z,
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


def test_tracking_without_a_registered_position_must_be_recomputed():
    assert _missing_registration([{"volume_cm3": 6.1}])
    assert not _missing_registration([{"volume_cm3": 6.1, "registered_z_mm": -95.0}])
    assert not _missing_registration([{"volume_cm3": 0.0}])
