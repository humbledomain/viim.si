#!/usr/bin/env python3
"""
VIIM — Virginia Roads (VDOT open data) helper.

Unlike the memoranda, VDOT's *spatial* data does have a real API. Virginia Roads
is an ArcGIS Hub site, so every dataset exposes an ArcGIS REST FeatureServer
endpoint: no key, no registration, JSON or GeoJSON out.

    https://www.virginiaroads.org/          browse datasets, copy the service URL
    https://data.virginia.gov/              CKAN mirror with its own API

This module is deliberately thin: discover the service URL for a dataset once,
put it in SERVICES below, then query it. Endpoint paths change when VDOT
republishes a layer, so verify before trusting any hardcoded URL.

    python3 tools/virginia-roads.py districts
    python3 tools/virginia-roads.py query --service districts --where "1=1" --fields DISTRICT_N
"""
import argparse, json, sys, urllib.parse, urllib.request

# Fill these in from virginiaroads.org → dataset → "I want to use this" → API/GeoJSON.
# Left empty on purpose: hardcoding an unverified endpoint is worse than none.
SERVICES = {
    # "districts": "https://services.arcgis.com/<org>/arcgis/rest/services/VDOT_Districts/FeatureServer/0",
    # "adt":       "https://services.arcgis.com/<org>/arcgis/rest/services/Traffic_Volume/FeatureServer/0",
    # "bridges":   "...",
    # "syip":      "...",
}

def query(service, where="1=1", fields="*", geometry=None, out_sr=4326, limit=200):
    """Standard ArcGIS REST query. Returns parsed JSON."""
    params = {
        "where": where, "outFields": fields, "f": "json",
        "outSR": out_sr, "resultRecordCount": limit, "returnGeometry": "false",
    }
    if geometry:
        params.update({
            "geometry": json.dumps(geometry), "geometryType": "esriGeometryPoint",
            "inSR": 4326, "spatialRel": "esriSpatialRelIntersects", "distance": 500, "units": "esriSRUnit_Foot",
        })
    url = service.rstrip("/") + "/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "query"])
    ap.add_argument("--service")
    ap.add_argument("--where", default="1=1")
    ap.add_argument("--fields", default="*")
    a = ap.parse_args()

    if a.cmd == "list":
        if not SERVICES:
            print("No services configured yet.\n"
                  "Open https://www.virginiaroads.org/, pick a dataset, copy its FeatureServer URL,\n"
                  "and add it to SERVICES in this file.")
            return 0
        for k, v in SERVICES.items():
            print(f"{k:12} {v}")
        return 0

    svc = SERVICES.get(a.service, a.service)
    if not svc or svc.startswith("http") is False:
        sys.exit("give --service as a configured name or a full FeatureServer URL")
    print(json.dumps(query(svc, a.where, a.fields), indent=2)[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
