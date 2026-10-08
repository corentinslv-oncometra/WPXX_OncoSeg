"""Public metadata adapters adapted from OncoRadar's discovery workflow.

See docs/oncoradar-integration.md for provenance and deliberate differences.
No arbitrary URL fetching, image downloading, clinical data, or LLM calls.
"""

import json
from urllib.parse import quote

import httpx

ENDPOINTS = {
    "TCIA": "https://services.cancerimagingarchive.net/nbia-api/services/v1/getCollectionValues",
    "IDC": "https://api.imaging.datacommons.cancer.gov/v3/collections",
}


def fetch_catalog(registry):
    url = ENDPOINTS[registry]
    # Fixed endpoints, no redirects and a bounded response. Metadata only.
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            response.raise_for_status()
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 8_000_000:
                    raise ValueError("Catalog response exceeds 8 MB")
    payload = json.loads(content)
    if isinstance(payload, dict):
        payload = payload.get("collections", payload.get("results"))
    if not isinstance(payload, list):
        raise ValueError("Source returned an unsupported catalog response")
    if len(payload) > 5000:
        raise ValueError("Catalog exceeds the bounded discovery limit; no partial refresh was published")
    records = []
    for entry in payload:
        if registry == "TCIA":
            name = entry.get("Collection") if isinstance(entry, dict) else entry
            if not isinstance(name, str) or not name.strip():
                continue
            external_id = name.strip()
            # Do not invent a landing-page slug from a collection name.
            landing = "https://nbia.cancerimagingarchive.net/nbia-search/"
            modalities = []
            tumor_types = []
        else:
            if not isinstance(entry, dict) or not entry.get("collection_id"):
                continue
            external_id = str(entry["collection_id"])
            name = entry.get("collection_name") or external_id
            landing = "https://portal.imaging.datacommons.cancer.gov/collections/" + quote(external_id, safe="")
            raw = entry.get("image_types") or entry.get("modalities") or []
            if isinstance(raw, str):
                raw = [raw]
            modalities = sorted({"MR" if str(value).upper() == "MRI" else str(value).upper()
                                 for value in raw} & {"CT", "MR"})
            cancers = entry.get("cancer_types") or entry.get("cancer_type") or []
            tumor_types = cancers if isinstance(cancers, list) else [str(cancers)]
        if len(external_id) > 255 or len(str(name)) > 255:
            raise ValueError("Source identifier exceeds catalog limits")
        records.append({"registry": registry, "external_id": external_id, "name": str(name),
            "url": landing, "modalities": modalities, "tumor_types": tumor_types,
            "evidence": [{"field": "discovery", "url": url, "quote": external_id}],
            "raw": entry})
    if not records:
        raise ValueError("Source returned no recognizable collections; existing catalog retained")
    return records
