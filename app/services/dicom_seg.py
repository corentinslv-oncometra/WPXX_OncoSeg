"""Place a DICOM SEG tumor segment onto the CT grid already opened in the viewer."""

from pathlib import Path

import numpy as np
import pydicom
import SimpleITK as sitk

from app.services.imaging import read_dicom_series_from_dir

TUMOR_WORDS = ("tumor", "tumour", "mass", "lesion", "hcc", "neoplasm")


def is_tumor_text(label: str, description: str = "") -> bool:
    text = f"{label} {description}".lower()
    return any(word in text for word in TUMOR_WORDS)


def _tumor_numbers(dataset) -> set[int]:
    numbers = set()
    for item in getattr(dataset, "SegmentSequence", []):
        if is_tumor_text(str(getattr(item, "SegmentLabel", "")), str(getattr(item, "SegmentDescription", ""))):
            numbers.add(int(item.SegmentNumber))
    return numbers


def paint_frames(image, frames, positions, row_cosine, column_cosine, row_spacing, column_spacing) -> np.ndarray:
    """Raster binary frames into the CT array. frames are (row, column)."""
    size = np.array(image.GetSize(), dtype=int)
    mask = np.zeros(tuple(int(n) for n in reversed(size)), dtype=np.uint8)
    direction = np.array(image.GetDirection(), dtype=float).reshape(3, 3)
    origin = np.array(image.GetOrigin(), dtype=float)
    spacing = np.array(image.GetSpacing(), dtype=float)
    inverse = np.linalg.inv(direction)
    row_step = np.array(row_cosine, dtype=float) * float(column_spacing)
    column_step = np.array(column_cosine, dtype=float) * float(row_spacing)
    for frame, position in zip(frames, positions):
        rows, columns = np.nonzero(np.asarray(frame) > 0)
        if not len(rows):
            continue
        points = np.array(position, dtype=float) + columns[:, None] * row_step + rows[:, None] * column_step
        index = np.rint((inverse @ (points - origin).T).T / spacing).astype(int)
        keep = np.all((index >= 0) & (index < size), axis=1)
        chosen = index[keep]
        mask[chosen[:, 2], chosen[:, 1], chosen[:, 0]] = 1
    return mask


def referenced_series_uids(dataset) -> set[str]:
    found = set()
    sequences = [getattr(dataset, "ReferencedSeriesSequence", [])]
    for group in getattr(dataset, "SharedFunctionalGroupsSequence", []):
        sequences.append(getattr(group, "ReferencedSeriesSequence", []))
    for sequence in sequences:
        for item in sequence:
            uid = str(getattr(item, "SeriesInstanceUID", "") or "")
            if uid:
                found.add(uid)
    return found


def paint_on_grid(positions, frames, frame_positions, orientation, row_spacing, column_spacing, rows, columns) -> np.ndarray:
    """Copy each frame onto the CT slice whose ImagePositionPatient it matches.

    Slice order is the DICOM reader order. A series that steps toward decreasing
    patient Z still lines up, because the match uses the slice position itself.
    """
    grid = np.asarray(positions, dtype=float)
    mask = np.zeros((len(grid), int(rows), int(columns)), dtype=np.uint8)
    row_cosine = np.array(orientation[:3], dtype=float)
    column_cosine = np.array(orientation[3:], dtype=float)
    for frame, position in zip(frames, frame_positions):
        position = np.array(position, dtype=float)
        nearest = int(np.argmin(np.linalg.norm(grid - position, axis=1)))
        if float(np.linalg.norm(grid[nearest] - position)) > 1.5:
            continue
        selected = np.asarray(frame)
        ys, xs = np.nonzero(selected > 0)
        if not len(ys):
            continue
        delta = position - grid[nearest]
        points = delta + xs[:, None] * (float(column_spacing) * row_cosine) + ys[:, None] * (float(row_spacing) * column_cosine)
        col = np.rint(points @ row_cosine / float(column_spacing)).astype(int)
        row = np.rint(points @ column_cosine / float(row_spacing)).astype(int)
        keep = (col >= 0) & (col < columns) & (row >= 0) & (row < rows)
        mask[nearest, row[keep], col[keep]] = 1
    return mask


def _ct_grid(series_dir: Path):
    names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(series_dir))
    positions = []
    orientation = spacing = None
    rows = columns = 0
    uid = ""
    for name in names:
        header = pydicom.dcmread(name, stop_before_pixels=True, force=True)
        positions.append([float(value) for value in header.ImagePositionPatient])
        if orientation is None:
            orientation = [float(value) for value in header.ImageOrientationPatient]
            spacing = [float(value) for value in header.PixelSpacing]
            rows, columns = int(header.Rows), int(header.Columns)
            uid = str(header.SeriesInstanceUID)
    return uid, np.asarray(positions, dtype=float), orientation, spacing, rows, columns


def study_has_seg(series_dir: Path) -> bool:
    return bool(sibling_seg_files(series_dir))


def sibling_seg_files(series_dir: Path) -> list[Path]:
    study = series_dir.parent
    found = []
    if not study.is_dir():
        return found
    for sibling in sorted(path for path in study.iterdir() if path.is_dir() and path != series_dir):
        for dicom in sorted(sibling.glob("*.dcm")):
            try:
                dataset = pydicom.dcmread(str(dicom), stop_before_pixels=True, force=True)
            except Exception:
                continue
            if str(getattr(dataset, "Modality", "")).upper() == "SEG":
                found.append(dicom)
            break
    return found


def tumor_mask(image, seg_path: Path):
    dataset = pydicom.dcmread(str(seg_path), force=True)
    numbers = _tumor_numbers(dataset)
    if not numbers or not hasattr(dataset, "pixel_array"):
        return None
    pixels = dataset.pixel_array
    if pixels.ndim == 2:
        pixels = pixels[None, ...]
    shared = dataset.SharedFunctionalGroupsSequence[0]
    measures = shared.PixelMeasuresSequence[0]
    spacing = [float(value) for value in measures.PixelSpacing]
    orientation = [float(value) for value in shared.PlaneOrientationSequence[0].ImageOrientationPatient]
    frames = []
    positions = []
    for index, group in enumerate(dataset.PerFrameFunctionalGroupsSequence):
        number = int(group.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        if number not in numbers:
            continue
        frames.append(pixels[index])
        positions.append([float(value) for value in group.PlanePositionSequence[0].ImagePositionPatient])
    if not frames:
        return None
    mask = paint_frames(image, frames, positions, orientation[:3], orientation[3:], spacing[0], spacing[1])
    if not int(mask.sum()):
        return None
    return mask


def _tumor_frames(dataset):
    numbers = _tumor_numbers(dataset)
    if not numbers or not hasattr(dataset, "pixel_array"):
        return [], [], [], 0.0, 0.0
    pixels = dataset.pixel_array
    if pixels.ndim == 2:
        pixels = pixels[None, ...]
    shared = dataset.SharedFunctionalGroupsSequence[0]
    measures = shared.PixelMeasuresSequence[0]
    spacing = [float(value) for value in measures.PixelSpacing]
    orientation = [float(value) for value in shared.PlaneOrientationSequence[0].ImageOrientationPatient]
    frames, positions = [], []
    for index, group in enumerate(dataset.PerFrameFunctionalGroupsSequence):
        number = int(group.SegmentIdentificationSequence[0].ReferencedSegmentNumber)
        if number not in numbers:
            continue
        frames.append(pixels[index])
        positions.append([float(value) for value in group.PlanePositionSequence[0].ImagePositionPatient])
    if not frames:
        return [], [], [], 0.0, 0.0
    return frames, positions, orientation, spacing[0], spacing[1]


def tumor_mask_for_series(image, series_dir: Path):
    """Paint the tumor segment of the SEG that cites this CT series.

    The mask is then oriented the same way as the saved CT, so it lands on the
    same voxels in the viewer.
    """
    try:
        uid, positions, orientation, _spacing, rows, columns = _ct_grid(series_dir)
    except Exception:
        return None
    if not len(positions) or orientation is None:
        return None
    painted = None
    for path in sibling_seg_files(series_dir):
        try:
            dataset = pydicom.dcmread(str(path), force=True)
            cited = referenced_series_uids(dataset)
            if cited and uid not in cited:
                continue
            frames, frame_positions, seg_orientation, row_spacing, column_spacing = _tumor_frames(dataset)
            if not frames or not np.allclose(seg_orientation, orientation, atol=1e-3):
                continue
            candidate = paint_on_grid(
                positions, frames, frame_positions, seg_orientation, row_spacing, column_spacing, rows, columns,
            )
        except Exception:
            continue
        if int(candidate.sum()):
            painted = candidate
            break
    if painted is None:
        return None
    raw = read_dicom_series_from_dir(series_dir)
    if tuple(int(n) for n in raw.GetSize()) != (columns, rows, len(positions)):
        return None
    if painted.shape != tuple(reversed(raw.GetSize())):
        return None
    volume = sitk.GetImageFromArray(painted)
    volume.CopyInformation(raw)
    oriented = sitk.DICOMOrient(volume, "LPS")
    if tuple(int(n) for n in oriented.GetSize()) != tuple(int(n) for n in image.GetSize()):
        return None
    if not np.allclose(oriented.GetOrigin(), image.GetOrigin(), atol=1e-2):
        return None
    if not np.allclose(oriented.GetDirection(), image.GetDirection(), atol=1e-4):
        return None
    return sitk.GetArrayFromImage(oriented)


def write_reference(image, mask: np.ndarray, path: Path) -> None:
    reference = sitk.GetImageFromArray(mask.astype(np.uint8))
    reference.CopyInformation(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(reference, str(path), True)
