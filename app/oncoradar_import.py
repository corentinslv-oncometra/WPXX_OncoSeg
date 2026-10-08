"""Read a WP05 SQLite file without modifying it.

The copy keeps the dataset record and the local DICOM folder. The patient
index, accounts, and image bytes stay in WP05.
"""

import json
from pathlib import Path
import sqlite3


# Columns that belong to the patient index, not the dataset record.
PATIENT_SECTION = {"patients_indexed_at", "patients_index_error"}


def _decode(value):
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[:1] in "[{":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def read_oncoradar(path):
    database = Path(path).expanduser()
    if not database.is_file():
        raise ValueError("OncoRadar database was not found")
    if not database.read_bytes()[:16].startswith(b"SQLite format 3"):
        raise ValueError("That file is not a SQLite database")
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "datasets" not in tables:
            raise ValueError("That SQLite file has no dataset table")
        records = []
        for record in db.execute("SELECT * FROM datasets ORDER BY name"):
            row = {}
            for key in record.keys():
                if key in PATIENT_SECTION:
                    continue
                row[key] = _decode(record[key])
            if "dl_path" in row and not row["dl_path"]:
                row["dl_path"] = ""
            records.append(row)
    return {"schema": "oncometra.catalog-import.v2", "records": records}
