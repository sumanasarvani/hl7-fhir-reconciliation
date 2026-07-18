"""
batch_extract.py

Runs extract_fhir.py logic across every patient FHIR bundle in a folder,
skipping non-patient files (hospitalInformation*, practitionerInformation*).

Usage:
    python batch_extract.py <fhir_folder> --out-dir extracted --years 3 --reference-date 2026-07-17

Produces one extracted_<patient_id>.json per patient in --out-dir, plus
a summary.csv listing patient/encounter/observation counts for a quick sanity check.
"""

import json
import argparse
import os
import glob
import csv
from datetime import datetime, timedelta
from dateutil import parser as dateparser


def load_bundle(filepath):
    with open(filepath, "r") as f:
        return json.load(f)


def index_entries_by_type(bundle):
    by_type = {}
    for entry in bundle.get("entry", []):
        resource = entry.get("resource", {})
        rtype = resource.get("resourceType")
        if not rtype:
            continue
        by_type.setdefault(rtype, []).append(resource)
    return by_type


def extract_patient(by_type):
    patients = by_type.get("Patient", [])
    if not patients:
        return None
    p = patients[0]
    name_entry = (p.get("name") or [{}])[0]
    given = name_entry.get("given", [])
    family = name_entry.get("family", "")
    address_entry = (p.get("address") or [{}])[0]

    mrn = None
    ssn = None
    for ident in p.get("identifier", []):
        code = (ident.get("type", {}).get("coding") or [{}])[0].get("code")
        if code == "MR":
            mrn = ident.get("value")
        elif code == "SS":
            ssn = ident.get("value")

    return {
        "patient_id": p.get("id"),
        "mrn": mrn,
        "ssn": ssn,
        "family_name": family,
        "given_names": given,
        "gender": p.get("gender"),
        "birth_date": p.get("birthDate"),
        "address_line": (address_entry.get("line") or [""])[0],
        "city": address_entry.get("city"),
        "state": address_entry.get("state"),
        "postal_code": address_entry.get("postalCode"),
        "phone": next(
            (t.get("value") for t in p.get("telecom", []) if t.get("system") == "phone"),
            None,
        ),
    }


def within_window(period_start_str, cutoff_dt):
    if not period_start_str:
        return False
    try:
        dt = dateparser.isoparse(period_start_str)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    return dt >= cutoff_dt


def extract_encounters(by_type, cutoff_dt):
    encounters = []
    for enc in by_type.get("Encounter", []):
        period = enc.get("period", {})
        start = period.get("start")
        if not within_window(start, cutoff_dt):
            continue
        participant = (enc.get("participant") or [{}])[0]
        provider_display = participant.get("individual", {}).get("display")
        reason_coding = (enc.get("reasonCode") or [{}])
        reason_text = None
        if reason_coding:
            codings = reason_coding[0].get("coding") or [{}]
            reason_text = codings[0].get("display")
        location_entry = (enc.get("location") or [{}])[0]
        location_display = location_entry.get("location", {}).get("display")

        encounters.append({
            "encounter_id": enc.get("id"),
            "status": enc.get("status"),
            "class_code": enc.get("class", {}).get("code"),
            "period_start": start,
            "period_end": period.get("end"),
            "reason": reason_text,
            "provider": provider_display,
            "location": location_display,
        })
    return encounters


def extract_lab_observations(by_type, encounter_ids):
    observations = []
    for obs in by_type.get("Observation", []):
        category_codes = [
            c.get("code")
            for cat in obs.get("category", [])
            for c in cat.get("coding", [])
        ]
        if "laboratory" not in category_codes:
            continue
        enc_ref = obs.get("encounter", {}).get("reference", "")
        enc_id = enc_ref.split(":")[-1] if enc_ref else None
        if enc_id not in encounter_ids:
            continue
        code_entry = (obs.get("code", {}).get("coding") or [{}])[0]
        value_qty = obs.get("valueQuantity", {})
        observations.append({
            "observation_id": obs.get("id"),
            "encounter_id": enc_id,
            "loinc_code": code_entry.get("code"),
            "display": code_entry.get("display"),
            "value": value_qty.get("value"),
            "unit": value_qty.get("unit"),
            "effective_datetime": obs.get("effectiveDateTime"),
            "issued": obs.get("issued"),
            "status": obs.get("status"),
        })
    return observations


def extract_one(filepath, cutoff_dt):
    bundle = load_bundle(filepath)
    by_type = index_entries_by_type(bundle)

    # Skip non-patient files (hospitalInformation*, practitionerInformation*)
    if "Patient" not in by_type:
        return None

    patient = extract_patient(by_type)
    encounters = extract_encounters(by_type, cutoff_dt)
    encounter_ids = {e["encounter_id"] for e in encounters}
    observations = extract_lab_observations(by_type, encounter_ids)

    return {
        "patient": patient,
        "encounters": encounters,
        "observations": observations,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fhir_folder", help="Folder containing Synthea FHIR bundle JSON files")
    parser.add_argument("--out-dir", default="extracted", help="Output directory for extracted JSON files")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--reference-date", default=None, help="ISO date to treat as 'today' (default: now)")
    args = parser.parse_args()

    ref_dt = dateparser.isoparse(args.reference_date) if args.reference_date else datetime.utcnow()
    cutoff_dt = ref_dt - timedelta(days=365 * args.years)

    os.makedirs(args.out_dir, exist_ok=True)

    all_files = sorted(glob.glob(os.path.join(args.fhir_folder, "*.json")))
    summary_rows = []
    skipped = 0
    processed = 0

    for filepath in all_files:
        result = extract_one(filepath, cutoff_dt)
        if result is None:
            skipped += 1
            continue

        patient_id = result["patient"]["patient_id"]
        out_path = os.path.join(args.out_dir, f"extracted_{patient_id}.json")
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)

        summary_rows.append({
            "patient_id": patient_id,
            "family_name": result["patient"]["family_name"],
            "num_encounters": len(result["encounters"]),
            "num_lab_observations": len(result["observations"]),
        })
        processed += 1

    summary_path = os.path.join(args.out_dir, "_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["patient_id", "family_name", "num_encounters", "num_lab_observations"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(f"Processed {processed} patients, skipped {skipped} non-patient files")
    print(f"Output written to: {args.out_dir}/")
    print(f"Summary: {summary_path}")
