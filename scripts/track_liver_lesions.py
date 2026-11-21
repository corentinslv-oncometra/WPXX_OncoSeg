"""Number one patient's liver lesions across time.

Each time folder needs image.nii.gz, organs.nii.gz and lesions.nii.gz on the
same grid. organs.nii.gz is the TotalSegmentator "total" mask (liver = 5).
Optional vessels.nii.gz and segments.nii.gz add hepatic vessels and Couinaud.

    python scripts/track_liver_lesions.py path/to/patient
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse

from app.services.lesion_tracking import LesionTrackingError, track_folder


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Suit les lésions hépatiques d’un patient à travers le temps.")
    parser.add_argument("patient", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--backend", choices=("sitk", "ants"), default="sitk")
    parser.add_argument("--liver-label", type=int, default=5)
    parser.add_argument("--min-voxels", type=int, default=4)
    parser.add_argument("--dilation-mm", type=float, default=3.0)
    args = parser.parse_args(argv)
    try:
        result = track_folder(
            args.patient, args.out, backend=args.backend, liver_labels=(args.liver_label,),
            min_voxels=args.min_voxels, dilation_mm=args.dilation_mm,
        )
    except LesionTrackingError as error:
        raise SystemExit(str(error)) from error
    print(f"{len(result.records)} lignes écrites. Référence {result.baseline}.")


if __name__ == "__main__":
    main()
