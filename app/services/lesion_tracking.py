"""Track liver lesions across time using the liver as a stable coordinate system.

Each exam keeps its own tumor mask. Lesions are split inside a slightly dilated
liver, then later exams are warped onto the baseline liver (not onto the
tumors). Official ids are assigned once and reused when a follow-up lesion
overlaps that history or sits near its centroid.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import SimpleITK as sitk
from scipy.ndimage import binary_dilation, label
from scipy.optimize import linear_sum_assignment

from app.services.exam_autoseg import mask_matches_image

logger = logging.getLogger(__name__)

# TotalSegmentator task "total": liver is label 5.
TOTAL_LIVER_LABEL = 5
MIN_VOXELS = 4
DILATION_MM = 3.0
SIGMA_MM = 15.0
MAX_DISTANCE_MM = 25.0
MIN_DICE = 0.1
DICE_WEIGHT = 0.6
DISTANCE_WEIGHT = 0.4
RECIST_RESPONSE = 0.30
RECIST_PROGRESSION = 0.20
NOUVELLE = "nouvelle"
DISPARUE = "disparue"
STABLE = "stable"
REPONSE = "réponse"
PROGRESSION = "progression"
_NEIGHBOR_26 = np.ones((3, 3, 3), dtype=int)


class LesionTrackingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Exam:
    """One timepoint. Arrays are z, y, x. Spacing and origin are x, y, z in millimetres."""

    time_id: str
    ct: np.ndarray
    organs: np.ndarray
    lesions: np.ndarray
    spacing_mm: tuple[float, float, float]
    origin_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    direction: tuple[float, ...] = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)
    vessels: np.ndarray | None = None
    segments: np.ndarray | None = None


@dataclass(frozen=True)
class LesionView:
    """One lesion on the baseline grid, plus the baseline shape when it differs from the latest one."""

    lesion_id: int
    mask: np.ndarray
    centroid_mm: tuple[float, float, float]
    alternate_mask: np.ndarray | None = None
    alternate_centroid_mm: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class LesionRecord:
    lesion_id: int
    time_id: str
    status: str
    volume_cm3: float | None
    long_axis_3d_mm: float | None
    long_axis_axial_mm: float | None
    hu_mean: float | None
    couinaud: int | None
    axial_index: int | None = None
    z_mm: float | None = None
    registered_z_mm: float | None = None

    def as_dict(self) -> dict:
        return {
            "lesion_id": self.lesion_id,
            "time_id": self.time_id,
            "status": self.status,
            "volume_cm3": _round(self.volume_cm3),
            "long_axis_3d_mm": _round(self.long_axis_3d_mm),
            "long_axis_axial_mm": _round(self.long_axis_axial_mm),
            "hu_mean": _round(self.hu_mean),
            "couinaud": self.couinaud,
            "axial_index": self.axial_index,
            "z_mm": _round(self.z_mm),
            "registered_z_mm": _round(self.registered_z_mm),
        }


@dataclass(frozen=True)
class TrackingResult:
    baseline: str
    backend: str
    labels: dict[str, np.ndarray]
    records: list[LesionRecord]
    settings: dict


class AnatomyRegistrar(Protocol):
    def warp_labels(self, fixed: Exam, moving: Exam, labels: np.ndarray) -> np.ndarray:
        """Resample moving instance labels onto the baseline grid with nearest neighbour."""


@dataclass
class _Tracked:
    lesion_id: int
    baseline_mask: np.ndarray
    latest_mask: np.ndarray
    baseline_axis_mm: float


def extract_instances(
    lesions: np.ndarray,
    organs: np.ndarray,
    spacing_mm: tuple[float, float, float],
    *,
    liver_labels: tuple[int, ...] = (TOTAL_LIVER_LABEL,),
    min_voxels: int = MIN_VOXELS,
    dilation_mm: float = DILATION_MM,
) -> np.ndarray:
    """Keep tumor voxels inside the dilated liver and split them into 3D components."""
    liver = _liver_mask(organs, liver_labels)
    if dilation_mm > 0 and liver.any():
        liver = binary_dilation(liver, structure=_ball(spacing_mm, dilation_mm))
    tumor = (np.asarray(lesions) > 0) & liver
    labeled, count = label(tumor, structure=_NEIGHBOR_26)
    if count == 0:
        return np.zeros(lesions.shape, dtype=np.uint16)
    counts = np.bincount(labeled.ravel())
    kept = [index for index, voxels in enumerate(counts) if index > 0 and voxels >= min_voxels]
    instances = np.zeros(labeled.shape, dtype=np.uint16)
    for new_id, old_id in enumerate(kept, start=1):
        instances[labeled == old_id] = new_id
    return instances


def assign_lesions(
    references: list[LesionView],
    candidates: list[LesionView],
    *,
    sigma_mm: float = SIGMA_MM,
    max_distance_mm: float = MAX_DISTANCE_MM,
    min_dice: float = MIN_DICE,
) -> list[tuple[int, int]]:
    """One-to-one pairs (reference id, candidate id) that clear the Dice or distance gate."""
    if not references or not candidates or sigma_mm <= 0:
        return []
    cost = np.ones((len(references), len(candidates)), dtype=float)
    for row, reference in enumerate(references):
        for column, candidate in enumerate(candidates):
            score, dice_score, distance = _best_score(reference, candidate, sigma_mm)
            if distance < max_distance_mm or dice_score > min_dice:
                cost[row, column] = 1.0 - score
    rows, columns = linear_sum_assignment(cost)
    pairs = []
    for row, column in zip(rows, columns):
        if cost[row, column] < 1.0:
            pairs.append((references[row].lesion_id, candidates[column].lesion_id))
    return pairs


def track(
    exams: list[Exam],
    *,
    registrar: AnatomyRegistrar | None = None,
    backend: str = "sitk",
    liver_labels: tuple[int, ...] = (TOTAL_LIVER_LABEL,),
    min_voxels: int = MIN_VOXELS,
    dilation_mm: float = DILATION_MM,
    sigma_mm: float = SIGMA_MM,
    max_distance_mm: float = MAX_DISTANCE_MM,
    min_dice: float = MIN_DICE,
    report=None,
) -> TrackingResult:
    """Number lesions on the first exam, then carry those ids forward in baseline space."""
    if not exams:
        raise LesionTrackingError("Aucun examen à suivre.")
    if len({exam.time_id for exam in exams}) != len(exams):
        raise LesionTrackingError("Deux examens portent le même identifiant de temps.")
    if registrar is None:
        registrar = make_registrar(backend, liver_labels)
    baseline = exams[0]
    count = len(exams)

    def tell(step: int, detail: str) -> None:
        if report is not None:
            report(min(90, 8 + int(82 * step / count)), detail)

    tell(0, f"Numérotation des lésions du {baseline.time_id}…")
    _validate(baseline)
    _require_liver(baseline, liver_labels)
    local = extract_instances(
        baseline.lesions, baseline.organs, baseline.spacing_mm,
        liver_labels=liver_labels, min_voxels=min_voxels, dilation_mm=dilation_mm,
    )
    official, catalog = _open_catalog(local, baseline)
    labels = {baseline.time_id: official}
    records = [_record(item.lesion_id, baseline, official, NOUVELLE) for item in catalog]
    for index, exam in enumerate(exams[1:], start=1):
        tell(index, f"Recalage du foie du {exam.time_id} sur {baseline.time_id}…")
        _validate(exam)
        _require_liver(exam, liver_labels)
        labels[exam.time_id], born = _carry(
            exam, baseline, catalog, registrar, liver_labels, min_voxels, dilation_mm,
            sigma_mm, max_distance_mm, min_dice,
        )
        records.extend(born)
    if report is not None:
        report(92, "Écriture du suivi…")
    return TrackingResult(
        baseline=baseline.time_id,
        backend=_backend_name(registrar),
        labels=labels,
        records=records,
        settings={
            "sigma_mm": sigma_mm,
            "max_distance_mm": max_distance_mm,
            "min_dice": min_dice,
            "dilation_mm": dilation_mm,
            "min_voxels": min_voxels,
            "liver_labels": list(liver_labels),
            "times": [exam.time_id for exam in exams],
        },
    )


def load_exam(folder: Path) -> Exam:
    """Read one time folder. Organs, lesions and the optional extras must share the CT grid."""
    folder = Path(folder)
    for name in ("image.nii.gz", "organs.nii.gz", "lesions.nii.gz"):
        if not (folder / name).is_file():
            raise LesionTrackingError(f"{folder.name} : {name} est absent.")
    ct = sitk.ReadImage(str(folder / "image.nii.gz"))
    organs = _read_mask(folder / "organs.nii.gz", ct)
    lesions = _read_mask(folder / "lesions.nii.gz", ct)
    vessels = _read_mask(folder / "vessels.nii.gz", ct) if (folder / "vessels.nii.gz").is_file() else None
    segments = _read_mask(folder / "segments.nii.gz", ct) if (folder / "segments.nii.gz").is_file() else None
    return Exam(
        time_id=folder.name,
        ct=sitk.GetArrayFromImage(ct).astype(np.float32, copy=False),
        organs=_as_labels(organs),
        lesions=_as_labels(lesions),
        spacing_mm=tuple(float(value) for value in ct.GetSpacing()),
        origin_mm=tuple(float(value) for value in ct.GetOrigin()),
        direction=tuple(float(value) for value in ct.GetDirection()),
        vessels=None if vessels is None else _as_labels(vessels),
        segments=None if segments is None else _as_labels(segments),
    )


def track_folder(patient: Path, out: Path | None = None, **kwargs) -> TrackingResult:
    """Track every time folder that contains image.nii.gz and write masks plus tracking.json."""
    patient = Path(patient)
    if not patient.is_dir():
        raise LesionTrackingError(f"Dossier patient introuvable : {patient}")
    times = sorted(path for path in patient.iterdir() if path.is_dir() and (path / "image.nii.gz").is_file())
    if not times:
        raise LesionTrackingError(f"Aucun temps avec image.nii.gz dans {patient}.")
    exams = [load_exam(path) for path in times]
    result = track(exams, **kwargs)
    write_result(result, exams, Path(out) if out is not None else patient / "tracking")
    return result


def write_result(result: TrackingResult, exams: list[Exam], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    geometry = {exam.time_id: exam for exam in exams}
    for time_id, labels in result.labels.items():
        image = _sitk_image(np.asarray(labels, dtype=np.uint16), geometry[time_id])
        sitk.WriteImage(image, str(folder / f"{_safe_name(time_id)}.nii.gz"), True)
    payload = {
        "baseline": result.baseline,
        "backend": result.backend,
        **result.settings,
        "lesions": [record.as_dict() for record in result.records],
    }
    (folder / "tracking.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def make_registrar(backend: str, liver_labels: tuple[int, ...] = (TOTAL_LIVER_LABEL,)) -> AnatomyRegistrar:
    if backend == "sitk":
        return SimpleItkAnatomyRegistrar(liver_labels=liver_labels)
    if backend == "ants":
        return AntsAnatomyRegistrar(liver_labels=liver_labels)
    raise LesionTrackingError("Recalage inconnu. Choisis sitk ou ants.")


class SimpleItkAnatomyRegistrar:
    """Affine alignment of the liver, then a demons step that only sees the liver."""

    def __init__(self, *, liver_labels: tuple[int, ...] = (TOTAL_LIVER_LABEL,), affine_iterations: int = 80, demons_iterations: int = 25):
        self.liver_labels = liver_labels
        self.affine_iterations = affine_iterations
        self.demons_iterations = demons_iterations

    def warp_labels(self, fixed: Exam, moving: Exam, labels: np.ndarray) -> np.ndarray:
        fixed_anatomy = _anatomy_image(fixed, self.liver_labels)
        moving_anatomy = _anatomy_image(moving, self.liver_labels)
        initial = sitk.CenteredTransformInitializer(
            fixed_anatomy, moving_anatomy, sitk.AffineTransform(3), sitk.CenteredTransformInitializerFilter.GEOMETRY,
        )
        affine = _optimize_affine(fixed_anatomy, moving_anatomy, initial, self.affine_iterations)
        liver = _sitk_image(_liver_mask(fixed.organs, self.liver_labels).astype(np.uint8), fixed)
        transform = _add_liver_demons(fixed_anatomy, moving_anatomy, affine, self.demons_iterations, liver)
        moving_labels = _sitk_image(np.asarray(labels, dtype=np.uint16), moving)
        warped = sitk.Resample(moving_labels, fixed_anatomy, transform, sitk.sitkNearestNeighbor, 0, sitk.sitkUInt16)
        array = np.rint(sitk.GetArrayFromImage(warped)).astype(np.uint16)
        if array.shape != fixed.ct.shape:
            raise LesionTrackingError("Le masque recalé n’est pas sur la grille de référence.")
        return array


class AntsAnatomyRegistrar:
    """Same liver-to-liver registration through ANTsPy SyN, used when antspyx is installed."""

    def __init__(self, *, liver_labels: tuple[int, ...] = (TOTAL_LIVER_LABEL,)):
        self.liver_labels = liver_labels

    def warp_labels(self, fixed: Exam, moving: Exam, labels: np.ndarray) -> np.ndarray:
        try:
            import ants
        except ImportError as error:
            raise LesionTrackingError(
                "antspyx n’est pas installé. Installe-le avec pip install antspyx, ou laisse le recalage SimpleITK."
            ) from error
        fixed_anatomy = _ants_image(ants, _anatomy_array(fixed, self.liver_labels), fixed)
        moving_anatomy = _ants_image(ants, _anatomy_array(moving, self.liver_labels), moving)
        liver = _ants_image(ants, _liver_mask(fixed.organs, self.liver_labels).astype(np.uint8), fixed)
        registration = ants.registration(fixed_anatomy, moving_anatomy, type_of_transform="SyNRA", mask=liver, verbose=False)
        moving_labels = _ants_image(ants, np.transpose(np.asarray(labels), (2, 1, 0)).astype(np.float32), moving)
        warped = ants.apply_transforms(fixed_anatomy, moving_labels, registration["fwdtransforms"], interpolator="nearestNeighbor")
        return np.rint(np.transpose(warped.numpy(), (2, 1, 0))).astype(np.uint16)


def _carry(exam, baseline, catalog, registrar, liver_labels, min_voxels, dilation_mm, sigma_mm, max_distance_mm, min_dice):
    local = extract_instances(
        exam.lesions, exam.organs, exam.spacing_mm,
        liver_labels=liver_labels, min_voxels=min_voxels, dilation_mm=dilation_mm,
    )
    official = np.zeros(local.shape, dtype=np.uint16)
    local_ids = _positive_ids(local)
    if not local_ids:
        return official, _missing_records(exam.time_id, catalog, set())
    try:
        warped = registrar.warp_labels(baseline, exam, local)
    except LesionTrackingError:
        raise
    except Exception as error:
        raise LesionTrackingError(f"{exam.time_id} : le recalage du foie a échoué ({error}).") from error
    candidates = _views(warped, _positive_ids(warped), baseline)
    references = [_catalog_view(item, baseline) for item in catalog]
    local_to_official = {
        local_id: official_id
        for official_id, local_id in assign_lesions(
            references, candidates, sigma_mm=sigma_mm, max_distance_mm=max_distance_mm, min_dice=min_dice,
        )
    }
    used: set[int] = set()
    records = []
    for local_id, official_id in local_to_official.items():
        official[local == local_id] = official_id
        item = _find(catalog, official_id)
        item.latest_mask = warped == local_id
        records.append(_record(
            official_id, exam, official,
            _lesion_status(_axis(official, official_id, exam), item.baseline_axis_mm),
            registered_z_mm=_registered_z(warped == local_id, baseline),
        ))
        used.add(official_id)
    fresh = [local_id for local_id in local_ids if local_id not in local_to_official]
    fresh.sort(key=lambda local_id: _rank_key(local, local_id, exam))
    next_id = 1 + max((item.lesion_id for item in catalog), default=0)
    for local_id in fresh:
        official[local == local_id] = next_id
        mask = warped == local_id
        if not mask.any():
            mask = np.zeros(baseline.ct.shape, dtype=bool)
        axis = _axis(official, next_id, exam)
        catalog.append(_Tracked(next_id, mask, mask, axis))
        records.append(_record(next_id, exam, official, NOUVELLE, registered_z_mm=_registered_z(mask, baseline)))
        used.add(next_id)
        next_id += 1
    records.extend(_missing_records(exam.time_id, catalog, used))
    records.sort(key=lambda record: record.lesion_id)
    return official, records


def _open_catalog(local: np.ndarray, exam: Exam) -> tuple[np.ndarray, list[_Tracked]]:
    ranked = sorted(_positive_ids(local), key=lambda local_id: _rank_key(local, local_id, exam))
    official = np.zeros(local.shape, dtype=np.uint16)
    catalog = []
    for official_id, local_id in enumerate(ranked, start=1):
        official[local == local_id] = official_id
        mask = official == official_id
        catalog.append(_Tracked(official_id, mask, mask, _axis(official, official_id, exam)))
    return official, catalog


def _catalog_view(item: _Tracked, exam: Exam) -> LesionView:
    latest = item.latest_mask.astype(bool, copy=False)
    alternate = None
    alternate_centroid = None
    if item.baseline_mask is not item.latest_mask and item.baseline_mask.any():
        alternate = item.baseline_mask.astype(bool, copy=False)
        alternate_centroid = _centroid_mm(alternate, exam)
    centroid = _centroid_mm(latest, exam) if latest.any() else (alternate_centroid or (0.0, 0.0, 0.0))
    return LesionView(item.lesion_id, latest, centroid, alternate, alternate_centroid)


def _views(labels: np.ndarray, ids: list[int], exam: Exam) -> list[LesionView]:
    views = []
    for lesion_id in ids:
        mask = labels == lesion_id
        if mask.any():
            views.append(LesionView(lesion_id, mask, _centroid_mm(mask, exam)))
    return views


def _record(lesion_id: int, exam: Exam, labels: np.ndarray, status: str, registered_z_mm: float | None = None) -> LesionRecord:
    selected = labels == lesion_id
    count = int(np.count_nonzero(selected))
    if count == 0:
        return LesionRecord(lesion_id, exam.time_id, status, 0.0, None, None, None, None)
    voxel_mm3 = float(exam.spacing_mm[0] * exam.spacing_mm[1] * exam.spacing_mm[2])
    zyx = np.argwhere(selected)
    points = _index_mm(zyx, exam.spacing_mm)
    axial = int(np.rint(float(zyx[:, 0].mean())))
    z_mm = _centroid_mm(selected, exam)[2]
    return LesionRecord(
        lesion_id, exam.time_id, status, count * voxel_mm3 / 1000.0,
        _extent_mm(points), _axial_extent_mm(zyx, exam.spacing_mm),
        float(exam.ct[selected].astype(np.float64).mean()), _couinaud(exam.segments, selected),
        axial, z_mm, z_mm if registered_z_mm is None else float(registered_z_mm),
    )


def _registered_z(mask: np.ndarray, exam: Exam) -> float | None:
    if not np.any(mask):
        return None
    return _centroid_mm(mask, exam)[2]


def _missing_records(time_id: str, catalog: list[_Tracked], used: set[int]) -> list[LesionRecord]:
    return [
        LesionRecord(item.lesion_id, time_id, DISPARUE, 0.0, None, None, None, None)
        for item in catalog if item.lesion_id not in used
    ]


def _best_score(reference: LesionView, candidate: LesionView, sigma_mm: float) -> tuple[float, float, float]:
    observations = [(reference.mask, reference.centroid_mm)]
    if reference.alternate_mask is not None and reference.alternate_centroid_mm is not None:
        observations.append((reference.alternate_mask, reference.alternate_centroid_mm))
    best = (0.0, 0.0, math.inf)
    for mask, centroid in observations:
        if not np.any(mask):
            continue
        overlap = dice(candidate.mask, mask)
        distance = float(np.linalg.norm(np.subtract(candidate.centroid_mm, centroid)))
        score = DICE_WEIGHT * overlap + DISTANCE_WEIGHT * math.exp(-distance / sigma_mm)
        if score > best[0]:
            best = (score, overlap, distance)
    return best


def dice(left: np.ndarray, right: np.ndarray) -> float:
    intersection = int(np.count_nonzero(np.asarray(left, dtype=bool) & np.asarray(right, dtype=bool)))
    total = int(np.count_nonzero(left)) + int(np.count_nonzero(right))
    if total == 0:
        return 0.0
    return 2.0 * intersection / total


def _lesion_status(current_axis_mm: float, baseline_axis_mm: float) -> str:
    if baseline_axis_mm <= 0:
        return STABLE
    ratio = current_axis_mm / baseline_axis_mm
    if ratio <= 1.0 - RECIST_RESPONSE:
        return REPONSE
    if ratio >= 1.0 + RECIST_PROGRESSION:
        return PROGRESSION
    return STABLE


def _liver_mask(organs: np.ndarray, liver_labels: tuple[int, ...]) -> np.ndarray:
    selected = np.zeros(organs.shape, dtype=bool)
    for liver_label in liver_labels:
        selected |= np.asarray(organs) == int(liver_label)
    return selected


def _ball(spacing_mm: tuple[float, float, float], radius_mm: float) -> np.ndarray:
    spacing_zyx = (spacing_mm[2], spacing_mm[1], spacing_mm[0])
    radii = [max(0, int(math.ceil(radius_mm / step))) for step in spacing_zyx]
    axes = [np.arange(-radius, radius + 1) for radius in radii]
    zz, yy, xx = np.meshgrid(*axes, indexing="ij")
    distance = np.sqrt((zz * spacing_zyx[0]) ** 2 + (yy * spacing_zyx[1]) ** 2 + (xx * spacing_zyx[2]) ** 2)
    return distance <= radius_mm + 1e-6


def _anatomy_array(exam: Exam, liver_labels: tuple[int, ...]) -> np.ndarray:
    liver = _liver_mask(exam.organs, liver_labels)
    if not liver.any():
        raise LesionTrackingError(f"{exam.time_id} : le foie est absent. Le recalage attend le label TotalSegmentator {liver_labels[0]}.")
    volume = liver.astype(np.float32)
    if exam.vessels is not None:
        volume[np.asarray(exam.vessels) > 0] = 2.0
    return volume


def _anatomy_image(exam: Exam, liver_labels: tuple[int, ...]):
    return _sitk_image(_anatomy_array(exam, liver_labels), exam)


def _optimize_affine(fixed, moving, initial, iterations: int):
    method = sitk.ImageRegistrationMethod()
    method.SetMetricAsMeanSquares()
    method.SetMetricFixedMask(sitk.Cast(fixed > 0.5, sitk.sitkUInt8))
    if fixed.GetNumberOfPixels() > 200_000:
        method.SetMetricSamplingStrategy(method.RANDOM)
        method.SetMetricSamplingPercentage(0.2)
    else:
        method.SetMetricSamplingStrategy(method.NONE)
    method.SetInterpolator(sitk.sitkLinear)
    method.SetOptimizerAsRegularStepGradientDescent(1.0, 1e-4, iterations, 1e-6)
    method.SetOptimizerScalesFromPhysicalShift()
    method.SetInitialTransform(initial, inPlace=False)
    method.SetShrinkFactorsPerLevel([2, 1])
    method.SetSmoothingSigmasPerLevel([1, 0])
    method.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
    return method.Execute(fixed, moving)


def _add_liver_demons(fixed_anatomy, moving_anatomy, affine, iterations: int, liver_image):
    if iterations <= 0:
        return affine
    try:
        aligned = sitk.Resample(moving_anatomy, fixed_anatomy, affine, sitk.sitkLinear, 0.0, sitk.sitkFloat32)
        liver = sitk.Cast(liver_image > 0, sitk.sitkFloat32)
        demons = sitk.FastSymmetricForcesDemonsRegistrationFilter()
        demons.SetNumberOfIterations(iterations)
        demons.SetStandardDeviations(1.0)
        field = demons.Execute(sitk.Cast(fixed_anatomy, sitk.sitkFloat32) * liver, aligned * liver)
        composite = sitk.CompositeTransform(3)
        composite.AddTransform(affine)
        composite.AddTransform(sitk.DisplacementFieldTransform(field))
        return composite
    except RuntimeError:
        logger.warning("Recalage déformable du foie impossible, conservation de l’affine.")
        return affine


def _ants_image(ants, array: np.ndarray, exam: Exam):
    # from_numpy treats axis 0 as x, while these volumes are stored z, y, x.
    image = ants.from_numpy(
        np.transpose(array, (2, 1, 0)),
        origin=tuple(float(value) for value in exam.origin_mm),
        spacing=tuple(float(value) for value in exam.spacing_mm),
    )
    image.set_direction(np.asarray(exam.direction, dtype=float).reshape(3, 3))
    return image


def _sitk_image(array: np.ndarray, exam: Exam):
    image = sitk.GetImageFromArray(array)
    image.SetSpacing(tuple(float(value) for value in exam.spacing_mm))
    image.SetOrigin(tuple(float(value) for value in exam.origin_mm))
    image.SetDirection(tuple(float(value) for value in exam.direction))
    return image


def _read_mask(path: Path, ct):
    image = sitk.ReadImage(str(path))
    if not mask_matches_image(ct, image):
        raise LesionTrackingError(f"{path.parent.name} : {path.name} n’est pas sur la grille du CT.")
    return image


def _as_labels(image) -> np.ndarray:
    return np.rint(sitk.GetArrayFromImage(image)).astype(np.int32)


def _validate(exam: Exam) -> None:
    shapes = [exam.ct.shape, exam.organs.shape, exam.lesions.shape]
    if exam.vessels is not None:
        shapes.append(exam.vessels.shape)
    if exam.segments is not None:
        shapes.append(exam.segments.shape)
    if len({shape for shape in shapes}) != 1:
        raise LesionTrackingError(f"{exam.time_id} : le CT et les masques n’ont pas la même taille.")
    if len(exam.spacing_mm) != 3 or len(exam.origin_mm) != 3 or len(exam.direction) != 9:
        raise LesionTrackingError(f"{exam.time_id} : la géométrie du volume est incomplète.")


def _require_liver(exam: Exam, liver_labels: tuple[int, ...]) -> None:
    if not _liver_mask(exam.organs, liver_labels).any():
        raise LesionTrackingError(
            f"{exam.time_id} : le foie est absent. Le recalage attend le label TotalSegmentator {liver_labels[0]}."
        )


def _positive_ids(labels: np.ndarray) -> list[int]:
    return [int(value) for value in np.unique(labels) if int(value) > 0]


def _rank_key(labels: np.ndarray, lesion_id: int, exam: Exam) -> tuple:
    mask = labels == lesion_id
    return (-int(np.count_nonzero(mask)), _centroid_mm(mask, exam))


def _axis(labels: np.ndarray, lesion_id: int, exam: Exam) -> float:
    zyx = np.argwhere(labels == lesion_id)
    return _axial_extent_mm(zyx, exam.spacing_mm)


def _centroid_mm(mask: np.ndarray, exam: Exam) -> tuple[float, float, float]:
    zyx = np.argwhere(mask)
    index_xyz = np.stack([zyx[:, 2], zyx[:, 1], zyx[:, 0]], axis=1).astype(float).mean(axis=0)
    spacing = np.asarray(exam.spacing_mm, dtype=float)
    origin = np.asarray(exam.origin_mm, dtype=float)
    direction = np.asarray(exam.direction, dtype=float).reshape(3, 3)
    point = origin + direction @ (index_xyz * spacing)
    return (float(point[0]), float(point[1]), float(point[2]))


def _index_mm(zyx: np.ndarray, spacing_mm: tuple[float, float, float]) -> np.ndarray:
    return np.stack([zyx[:, 2] * spacing_mm[0], zyx[:, 1] * spacing_mm[1], zyx[:, 0] * spacing_mm[2]], axis=1)


def _extent_mm(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    centered = points - points.mean(axis=0)
    _, _, singular = np.linalg.svd(centered, full_matrices=False)
    projected = centered @ singular[0]
    return float(projected.max() - projected.min())


def _axial_extent_mm(zyx: np.ndarray, spacing_mm: tuple[float, float, float]) -> float:
    best = 0.0
    for depth in np.unique(zyx[:, 0]):
        slice_points = zyx[zyx[:, 0] == depth]
        plane = np.stack([slice_points[:, 2] * spacing_mm[0], slice_points[:, 1] * spacing_mm[1]], axis=1)
        best = max(best, _extent_mm(plane))
    return best


def _couinaud(segments: np.ndarray | None, selected: np.ndarray) -> int | None:
    if segments is None:
        return None
    values = np.asarray(segments)[selected]
    values = values[values > 0].astype(np.int64, copy=False)
    if values.size == 0:
        return None
    return int(np.bincount(values).argmax())


def _find(catalog: list[_Tracked], lesion_id: int) -> _Tracked:
    for item in catalog:
        if item.lesion_id == lesion_id:
            return item
    raise LesionTrackingError(f"Lésion {lesion_id} absente du catalogue.")


def _backend_name(registrar: AnatomyRegistrar) -> str:
    if isinstance(registrar, SimpleItkAnatomyRegistrar):
        return "sitk"
    if isinstance(registrar, AntsAnatomyRegistrar):
        return "ants"
    return "custom"


def _safe_name(time_id: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in time_id)
    return cleaned or "time"


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 3)
