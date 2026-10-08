"""Read an OncoRadar SQLite snapshot without modifying it; emit catalog JSON.

The file includes the dataset record and the local DICOM folder. It does not
include the patient index, accounts, passwords, or image bytes.
Large indexes are easier to load with Datasets → Sync OncoRadar index.
"""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.oncoradar_import import read_oncoradar


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", help="Path to an OncoRadar SQLite backup, opened read-only")
    args = parser.parse_args()
    json.dump(read_oncoradar(args.database), sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
