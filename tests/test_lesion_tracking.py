import json
from pathlib import Path

import numpy as np
import pytest
import SimpleITK as sitk

from app.services.lesion_tracking import (
    DISPARUE, DIVISION, FUSION, FUSIONNEE, NOUVELLE, PROGRESSION, REPONSE, STABLE,
    Exam, LesionTrackingError, LesionView,
    SimpleItkAnatomyRegistrar, _anatomy_image, _centroid_mm, _initial_affine, assign_lesions, dice, extract_instances,
    hausdorff95_mm, load_exam, make_registrar, organ_agreement, track, track_folder,
)


class _Identity:
    def warp_labels(self, fixed, moving, labels):
        return np.asarray(labels)


def _exam(time_id, organs, lesions, ct=None, segments=None, spacing=(1.0, 1.0, 1.0)):
    organs = np.asarray(organs)
    ct = np.zeros(organs.shape, np.float32) if ct is None else np.asarray(ct, dtype=np.float32)
    return Exam(time_id, ct, organs.astype(np.int32), np.asarray(lesions).astype(np.int32), spacing, segments=None if segments is None else np.asarray(segments))


def _liver(shape):
    organs = np.zeros(shape, np.int32)
    organs[:] = 5
    return organs


def _box(shape, origin, size, value=1):
    mask = np.zeros(shape, np.int32)
    z, y, x = origin
    depth, height, width = size
    mask[z:z + depth, y:y + height, x:x + width] = value
    return mask


def test_every_lesion_is_kept_and_speckles_are_dropped():
    organs = np.zeros((8, 8, 16), np.int32)
    organs[:, :, 2:7] = 5
    lesions = np.zeros_like(organs)
    lesions[:, :, 3:5] = 1
    lesions[0:2, 0:2, 9] = 1
    lesions[0:2, 0:2, 14] = 1
    lesions[0, 0, 6] = 1
    lesions[0, 1, 6] = 1
    instances = extract_instances(lesions, organs, (1.0, 1.0, 1.0), min_voxels=4)
    assert np.count_nonzero(instances[:, :, 3:5]) == int(np.count_nonzero(lesions[:, :, 3:5]))
    assert np.count_nonzero(instances[:, :, 9]) == 4
    assert np.count_nonzero(instances[:, :, 14]) == 4
    assert np.count_nonzero(instances[:, :, 6]) == 0


def test_assignment_is_one_to_one_and_honours_both_gates():
    left = np.zeros((4, 4, 6), dtype=bool)
    right = np.zeros_like(left)
    left[:, :, 0:2] = True
    right[:, :, 4:6] = True
    near = LesionView(1, left, (1.0, 0.0, 0.0))
    assert assign_lesions([near], [LesionView(7, np.zeros_like(left), (30.0, 0.0, 0.0))]) == []
    assert assign_lesions([near], [LesionView(7, left, (1.0, 0.0, 0.0))]) == [(1, 7)]
    assert assign_lesions([near], [LesionView(7, np.zeros_like(left), (10.0, 0.0, 0.0))]) == [(1, 7)]
    pairs = assign_lesions(
        [LesionView(1, left, (0.0, 0.0, 0.0)), LesionView(2, right, (0.0, 0.0, 5.0))],
        [LesionView(10, right, (0.0, 0.0, 5.0)), LesionView(11, left, (0.0, 0.0, 0.0))],
    )
    assert sorted(pairs) == [(1, 11), (2, 10)]


def test_a_shrunk_lesion_keeps_its_number_and_a_distant_one_is_new():
    shape = (8, 8, 24)
    organs = _liver(shape)
    baseline = _box(shape, (2, 2, 4), (4, 4, 4))
    shrunk = _box(shape, (3, 3, 5), (2, 2, 2))
    other = _box(shape, (2, 2, 18), (3, 3, 3))
    follow = shrunk + other
    result = track([
        _exam("t0", organs, baseline, ct=np.full(shape, 40, np.float32)),
        _exam("t1", organs, follow, ct=np.full(shape, 80, np.float32)),
    ], registrar=_Identity(), min_voxels=4, dilation_mm=0)
    assert set(np.unique(result.labels["t1"])) == {0, 1, 2}
    assert np.array_equal(result.labels["t1"] == 1, shrunk.astype(bool))
    assert np.array_equal(result.labels["t1"] == 2, other.astype(bool))
    by_id = {(row.time_id, row.lesion_id): row for row in result.records}
    assert by_id[("t1", 1)].status == REPONSE
    assert by_id[("t1", 2)].status == NOUVELLE
    assert by_id[("t0", 1)].hu_mean == 40
    assert by_id[("t1", 1)].hu_mean == 80
    assert by_id[("t0", 1)].volume_cm3 == pytest.approx(64 / 1000)


def test_tracking_reports_each_date_before_the_result_is_written():
    shape = (8, 8, 16)
    organs = _liver(shape)
    lesion = _box(shape, (2, 2, 4), (3, 3, 3))
    notes = []
    track([
        _exam("1999-04-30", organs, lesion),
        _exam("1999-06-01", organs, lesion),
    ], registrar=_Identity(), min_voxels=4, dilation_mm=0, report=lambda percent, detail: notes.append((percent, detail)))
    assert [percent for percent, _detail in notes] == [8, 49, 92]
    assert "1999-04-30" in notes[0][1]
    assert "1999-06-01" in notes[1][1]
    assert notes[1][1].startswith("Recalage de l’anatomie")


def test_a_lesion_absent_from_the_previous_exam_receives_a_new_number():
    shape = (4, 4, 56)
    organs = _liver(shape)
    first = _box(shape, (1, 1, 4), (2, 2, 2))
    second = _box(shape, (1, 1, 23), (2, 2, 2))
    third = _box(shape, (1, 1, 42), (2, 2, 2))
    grown = _box(shape, (0, 0, 2), (4, 4, 6))
    exams = [
        _exam("t0", organs, first),
        _exam("t1", organs, second),
        _exam("t2", organs, third),
        _exam("t3", organs, np.zeros(shape)),
        _exam("t4", organs, grown),
    ]
    result = track(exams, registrar=_Identity(), min_voxels=4, dilation_mm=0)
    assert [row.status for row in result.records if row.lesion_id == 1] == [NOUVELLE, STABLE, STABLE, DISPARUE, DISPARUE]
    assert set(np.unique(result.labels["t4"])) == {0, 2}


def test_each_exam_is_compared_with_the_previous_one():
    shape = (4, 4, 80)
    organs = _liver(shape)
    first = _box(shape, (1, 1, 4), (2, 2, 2))
    second = _box(shape, (1, 1, 24), (2, 2, 2))
    third = _box(shape, (1, 1, 44), (2, 2, 2))
    seen = []

    class _Record:
        def warp_labels(self, fixed, moving, labels):
            seen.append((moving.time_id, fixed.time_id))
            return np.asarray(labels)

    result = track([
        _exam("t0", organs, first),
        _exam("t1", organs, second),
        _exam("t2", organs, third),
    ], registrar=_Record(), min_voxels=4, dilation_mm=0)
    assert seen == [("t1", "t0"), ("t2", "t1")]
    assert [row.status for row in result.records if row.lesion_id == 1] == [NOUVELLE, STABLE, STABLE]
    assert set(np.unique(result.labels["t2"])) == {0, 1}


def test_couinaud_is_the_majority_segment_and_the_largest_lesion_is_first():
    shape = (6, 6, 12)
    organs = _liver(shape)
    small = _box(shape, (1, 1, 1), (2, 2, 2))
    large = _box(shape, (1, 1, 6), (3, 3, 3))
    segments = np.zeros(shape, np.int32)
    segments[large > 0] = 6
    segments[1, 1, 6] = 4
    result = track([_exam("t0", organs, small + large, segments=segments)], registrar=_Identity(), min_voxels=4, dilation_mm=0)
    assert np.array_equal(result.labels["t0"] == 1, large.astype(bool))
    rows = {row.lesion_id: row for row in result.records}
    assert rows[1].couinaud == 6
    assert rows[2].couinaud is None


def test_folder_roundtrip_rejects_a_mask_on_another_grid(tmp_path):
    patient = tmp_path / "HCC_001"
    shape = (6, 6, 8)
    organs = _liver(shape)
    lesions = _box(shape, (2, 2, 2), (2, 2, 2))
    ct = np.full(shape, 30, np.float32)
    for name in ("2000-01-01", "2000-06-01"):
        _write_exam(patient / name, ct, organs, lesions)
    result = track_folder(patient, tmp_path / "out", registrar=_Identity(), min_voxels=4, dilation_mm=0)
    stored = sitk.GetArrayFromImage(sitk.ReadImage(str(tmp_path / "out" / "2000-06-01.nii.gz")))
    assert np.array_equal(stored, result.labels["2000-06-01"])
    payload = json.loads((tmp_path / "out" / "tracking.json").read_text(encoding="utf-8"))
    assert payload["baseline"] == "2000-01-01"
    assert payload["lesions"][1]["status"] == STABLE
    foreign = patient / "2000-06-01" / "lesions.nii.gz"
    image = sitk.ReadImage(str(foreign))
    image.SetSpacing((2.0, 2.0, 2.0))
    sitk.WriteImage(image, str(foreign), True)
    with pytest.raises(LesionTrackingError, match="grille"):
        load_exam(patient / "2000-06-01")


def test_one_distant_voxel_does_not_set_the_hausdorff_95():
    shape = (24, 24, 24)
    left = np.zeros(shape, dtype=bool)
    left[6:16, 6:16, 6:16] = True
    right = left.copy()
    right[6, 6, 22] = True
    assert hausdorff95_mm(left, right, (1.0, 1.0, 1.0)) < 1.0
    assert dice(left, right) > 0.9


def test_a_shifted_liver_lowers_the_dice_and_raises_the_hausdorff():
    shape = (20, 20, 20)
    left = np.zeros(shape, np.int32)
    right = np.zeros(shape, np.int32)
    left[4:14, 4:14, 4:14] = 5
    right[4:14, 4:14, 8:18] = 5
    row = organ_agreement("t1", "t0", left, right, (1.0, 1.0, 1.0), "liver")
    assert row.dice < 0.8
    assert 3.0 <= row.hd95_mm <= 5.0
    assert row.as_dict()["organ"] == "liver"


def test_the_followup_stores_the_lung_overlap_of_each_later_exam():
    shape = (12, 12, 12)
    organs = np.zeros(shape, np.int32)
    organs[2:10, 2:10, 2:10] = 10
    lesion = _box(shape, (4, 4, 4), (3, 3, 3))

    class _Reuse:
        def warp_labels(self, fixed, moving, labels):
            self.pair = (fixed, moving)
            return np.asarray(labels)

        def resample_with_last(self, fixed, moving, labels):
            assert (fixed, moving) == self.pair
            return np.asarray(labels)

    result = track([
        _exam("t0", organs, lesion),
        _exam("t1", organs, lesion),
    ], registrar=_Reuse(), min_voxels=4, dilation_mm=0, organ="lung")
    assert [(item.time_id, item.fixed_time_id, item.organ, item.dice, item.hd95_mm) for item in result.alignments] == [
        ("t1", "t0", "lung", 1.0, 0.0),
    ]


def test_registration_starts_on_the_cancer_organ_and_keeps_the_volume_center_without_it():
    fixed_organs = np.zeros((12, 8, 8), np.int32)
    moving_organs = np.zeros((36, 8, 8), np.int32)
    fixed_organs[1:4] = 10
    moving_organs[1:4] = 10
    fixed = _exam("t0", fixed_organs, np.zeros_like(fixed_organs))
    moving = _exam("t1", moving_organs, np.zeros_like(moving_organs))
    fixed_anatomy = _anatomy_image(fixed, (5,))
    moving_anatomy = _anatomy_image(moving, (5,))
    fixed_lung = _centroid_mm(fixed_organs == 10, fixed)
    moving_lung = _centroid_mm(moving_organs == 10, moving)
    started = _initial_affine(fixed_anatomy, moving_anatomy, fixed, moving, "lung", (5,))
    mapped = started.TransformPoint(fixed_lung)
    assert np.linalg.norm(np.subtract(mapped, moving_lung)) < 1
    volume = _initial_affine(fixed_anatomy, moving_anatomy, fixed, moving, "", (5,))
    assert np.linalg.norm(np.subtract(volume.TransformPoint(fixed_lung), moving_lung)) > 5
    liver = np.zeros((8, 8, 8), np.int32)
    liver[2:5] = 5
    head = _exam("head", liver, np.zeros_like(liver))
    other = _exam("other", liver, np.zeros_like(liver))
    head_anatomy = _anatomy_image(head, (5,))
    other_anatomy = _anatomy_image(other, (5,))
    missing = _initial_affine(head_anatomy, other_anatomy, head, other, "lung", (5,))
    geometric = _initial_affine(head_anatomy, other_anatomy, head, other, "", (5,))
    point = (1.0, 2.0, 3.0)
    assert np.allclose(missing.TransformPoint(point), geometric.TransformPoint(point))

    class _Recorded:
        organ = ""

        def warp_labels(self, fixed, moving, labels):
            self.seen = self.organ
            return np.zeros(fixed.ct.shape, np.uint16)

        def resample_with_last(self, fixed, moving, labels):
            return np.zeros(fixed.ct.shape, np.uint16)

    nodule = np.zeros((12, 8, 8), np.int32)
    nodule[1:4, 1:4, 1:4] = 1
    registrar = _Recorded()
    track([
        _exam("t0", fixed_organs, nodule),
        _exam("t1", fixed_organs, nodule),
    ], registrar=registrar, organ="lung", min_voxels=4, dilation_mm=0)
    assert registrar.seen == "lung"


def test_registration_brings_a_shifted_liver_lesion_back():
    shape = (16, 16, 32)
    fixed_liver = _ball(shape, (8, 8, 10), 5)
    moving_liver = _ball(shape, (8, 8, 15), 5)
    organs_fixed = np.where(fixed_liver, 5, 0).astype(np.int32)
    organs_moving = np.where(moving_liver, 5, 0).astype(np.int32)
    fixed_lesion = _box(shape, (7, 7, 9), (3, 3, 3))
    moving_lesion = _box(shape, (7, 7, 14), (3, 3, 3))
    fixed = _exam("t0", organs_fixed, fixed_lesion)
    moving = _exam("t1", organs_moving, moving_lesion)
    assert dice(fixed_lesion, moving_lesion) == 0
    warped = SimpleItkAnatomyRegistrar(affine_iterations=60, demons_iterations=15).warp_labels(fixed, moving, moving_lesion.astype(np.uint16))
    assert dice(warped > 0, fixed_lesion > 0) > 0
    result = track([fixed, moving], registrar=SimpleItkAnatomyRegistrar(affine_iterations=60, demons_iterations=15), min_voxels=4, dilation_mm=0)
    assert set(np.unique(result.labels["t1"])) == {0, 1}
    assert result.records[-1].status != NOUVELLE


def test_a_lesion_outside_the_liver_is_numbered():
    shape = (8, 8, 16)
    organs = np.zeros(shape, np.int32)
    organs[:, :, 12:16] = 12
    lesion = _box(shape, (2, 2, 12), (3, 3, 3))
    result = track([_exam("t0", organs, lesion)], registrar=_Identity(), min_voxels=4)
    assert int(np.count_nonzero(result.labels["t0"])) == int(np.count_nonzero(lesion))
    assert result.records[0].status == NOUVELLE


def test_alignment_needs_an_organ_and_an_unknown_backend_is_rejected():
    organs = np.zeros((4, 4, 4), np.int32)
    lesion = _box((4, 4, 4), (0, 0, 0), (2, 2, 2))
    with pytest.raises(LesionTrackingError, match="organe"):
        track([
            _exam("t0", organs, lesion),
            _exam("t1", organs, lesion),
        ], registrar=SimpleItkAnatomyRegistrar(affine_iterations=1, demons_iterations=0))
    with pytest.raises(LesionTrackingError, match="sitk ou ants"):
        make_registrar("elastix")


def test_ants_reports_a_missing_install():
    organs = _liver((4, 4, 4))
    lesions = _box((4, 4, 4), (1, 1, 1), (2, 2, 2))
    try:
        import ants  # noqa: F401
    except ImportError:
        with pytest.raises(LesionTrackingError, match="antspyx"):
            make_registrar("ants").warp_labels(_exam("t0", organs, lesions), _exam("t1", organs, lesions), lesions.astype(np.uint16))
    else:
        pytest.skip("antspyx est installé")


def test_a_split_keeps_the_same_number_on_both_parts():
    shape = (4, 4, 24)
    organs = _liver(shape)
    parent = _box(shape, (0, 0, 4), (4, 4, 12))
    left = _box(shape, (0, 0, 4), (4, 4, 5))
    right = _box(shape, (0, 0, 11), (4, 4, 5))
    result = track([
        _exam("t0", organs, parent),
        _exam("t1", organs, left + right),
    ], registrar=_Identity(), min_voxels=4)
    labels = result.labels["t1"]
    assert set(np.unique(labels)) == {0, 1}
    assert np.array_equal(labels == 1, (left + right).astype(bool))
    split_rows = [row for row in result.records if row.time_id == "t1" and row.event == DIVISION]
    assert [row.lesion_id for row in split_rows] == [1]
    assert split_rows[0].status == DIVISION
    assert int(np.count_nonzero(labels == 1)) == int(np.count_nonzero(left)) + int(np.count_nonzero(right))


def test_a_speck_inside_a_lesion_does_not_count_as_a_split():
    shape = (4, 4, 24)
    organs = _liver(shape)
    parent = _box(shape, (0, 0, 2), (4, 4, 16))
    kept = _box(shape, (0, 0, 2), (4, 4, 12))
    speck = _box(shape, (0, 0, 16), (2, 2, 2))
    result = track([
        _exam("t0", organs, parent),
        _exam("t1", organs, kept + speck),
    ], registrar=_Identity(), min_voxels=4)
    assert np.array_equal(result.labels["t1"] == 1, kept.astype(bool))
    assert set(np.unique(result.labels["t1"])) == {0, 1, 2}
    assert all(row.event != DIVISION for row in result.records)


def test_two_lesions_that_merge_keep_both_parents_on_the_new_number():
    shape = (4, 4, 24)
    organs = _liver(shape)
    left = _box(shape, (0, 0, 2), (4, 4, 4))
    right = _box(shape, (0, 0, 12), (4, 4, 4))
    merged = _box(shape, (0, 0, 2), (4, 4, 14))
    result = track([
        _exam("t0", organs, left + right),
        _exam("t1", organs, merged),
    ], registrar=_Identity(), min_voxels=4)
    assert set(np.unique(result.labels["t1"])) == {0, 3}
    child = next(row for row in result.records if row.time_id == "t1" and row.status == FUSION)
    assert child.status == FUSION
    assert set(child.parent_ids) == {1, 2}
    parents = [row for row in result.records if row.time_id == "t1" and row.status == FUSIONNEE]
    assert {row.lesion_id for row in parents} == {1, 2}
    assert all(row.child_ids == (3,) for row in parents)


def test_parts_that_still_touch_by_a_corner_stay_one_component():
    shape = (6, 6, 6)
    organs = _liver(shape)
    mask = np.zeros(shape, np.int32)
    mask[1:3, 1:3, 1:3] = 1
    mask[3:5, 3:5, 3:5] = 1
    instances = extract_instances(mask, organs, (1.0, 1.0, 1.0), min_voxels=4)
    assert set(np.unique(instances)) == {0, 1}


def _ball(shape, center, radius):
    zz, yy, xx = np.ogrid[0:shape[0], 0:shape[1], 0:shape[2]]
    return (zz - center[0]) ** 2 + (yy - center[1]) ** 2 + (xx - center[2]) ** 2 <= radius ** 2


def _write_exam(folder: Path, ct, organs, lesions) -> None:
    folder.mkdir(parents=True)
    for name, array in (("image.nii.gz", ct), ("organs.nii.gz", organs), ("lesions.nii.gz", lesions)):
        image = sitk.GetImageFromArray(np.asarray(array))
        image.SetSpacing((1.0, 1.2, 1.5))
        sitk.WriteImage(image, str(folder / name), True)
