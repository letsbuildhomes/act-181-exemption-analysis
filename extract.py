#!/usr/bin/env python3
"""
extract.py

Downloads the Vermont New Housing dataset from the ArcGIS REST API and writes
it to data/dhcd_housing.csv, overwriting any existing file.

Source: Vermont_New_Housing FeatureServer (~16,000 records)
"""

import json
import csv
import urllib.request
import urllib.parse
import os

BASE = "https://services1.arcgis.com/BkFxaEFNwHqX3tAw/arcgis/rest/services"
PAGE_SIZE = 1000
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "dhcd_housing.csv")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def query_all(service_name, layer=0, where="1=1"):
    """Paginate through all records in a FeatureServer layer."""
    base_url = f"{BASE}/{service_name}/FeatureServer/{layer}/query"
    all_features = []
    offset = 0

    while True:
        params = {
            "where": where,
            "outFields": "*",
            "returnGeometry": "true",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE_SIZE,
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        data = fetch_json(url)
        features = data.get("features", [])
        all_features.extend(features)
        print(f"  fetched {len(all_features)} records...", end="\r")

        if len(features) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    print(f"  {len(all_features)} total records fetched.    ")
    return all_features


def features_to_csv(features, out_path):
    """Write GeoJSON features to CSV with lon/lat columns appended."""
    if not features:
        print("  No features to write.")
        return

    fieldnames = list(features[0]["properties"].keys())

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + ["longitude", "latitude"])
        writer.writeheader()
        for feat in features:
            row = dict(feat["properties"])
            coords = feat.get("geometry") or {}
            if coords.get("coordinates"):
                row["longitude"] = coords["coordinates"][0]
                row["latitude"] = coords["coordinates"][1]
            else:
                row["longitude"] = ""
                row["latitude"] = ""
            writer.writerow(row)

    size_kb = os.path.getsize(out_path) / 1024
    print(f"  Saved: {out_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    print("Downloading Vermont New Housing data...")
    housing = query_all("Vermont_New_Housing")
    features_to_csv(housing, OUT_PATH)
    print("Done.")
