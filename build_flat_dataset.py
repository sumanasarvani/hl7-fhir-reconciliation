"""
build_flat_dataset.py

Reads extracted patient JSON files (output of batch_extract.py) and produces:
  - patients_fhir.csv     : one row per lab result, FHIR-derived (the "correct" source)
  - patients_hl7.csv      : same shape, but ~15% of rows have a deliberate mistake
  - ground_truth_discrepancies.csv : the answer key -- exactly what was changed and how

This replaces the earlier multi-table / raw-HL7-message approach with a single
flat, denormalized structure that's easy to load and easy to reconcile in Snowflake.

Usage:
    python build_flat_dataset.py extracted/ --n-patients 50 --out-dir flat_dataset --seed 42
"""

import json
import csv
import glob
import os
import random
import argparse
from datetime import datetime, timedelta


def load_patients_with_data(extracted_dir, n_patients, seed):
    """Load patient JSONs, keep only ones with at least 1 encounter, pick n_patients."""
    random.seed(seed)
    all_files = sorted(glob.glob(os.path.join(extracted_dir, "extracted_*.json")))

    candidates = []
    for filepath in all_files:
        with open(filepath, "r") as f:
            data = json.load(f)
        if data.get("encounters"):  # skip patients with zero encounters
            candidates.append(data)

    if len(candidates) < n_patients:
        print(f"WARNING: only {len(candidates)} patients have encounter data, "
              f"using all of them instead of {n_patients}")
        return candidates

    return random.sample(candidates, n_patients)


def flatten_patient_fhir(patient_json):
    """One row per lab observation, with patient + encounter info repeated on each row."""
    rows = []
    patient = patient_json["patient"]
    encounters_by_id = {e["encounter_id"]: e for e in patient_json["encounters"]}

    for obs in patient_json["observations"]:
        enc = encounters_by_id.get(obs["encounter_id"], {})
        given = " ".join(patient.get("given_names", []) or [])
        rows.append({
            "observation_id": obs["observation_id"],  # stable unique key -- carries through to HL7 side unchanged
            "patient_id": patient["patient_id"],
            "patient_name": f"{given} {patient['family_name']}".strip(),
            "dob": patient["birth_date"],
            "gender": patient["gender"],
            "encounter_id": obs["encounter_id"],
            "encounter_date": enc.get("period_start", ""),
            "provider": enc.get("provider", ""),
            "lab_code": obs["loinc_code"],
            "lab_name": obs["display"],
            "lab_value": obs["value"],
            "lab_unit": obs["unit"],
        })
    return rows


def shift_date(date_str, hours_range=(1, 4)):
    """Shift an ISO datetime string by 1-4 hours, in either direction."""
    if not date_str:
        return date_str
    try:
        dt = datetime.fromisoformat(date_str)
    except ValueError:
        return date_str
    shift = random.choice([1, -1]) * random.randint(*hours_range)
    return (dt + timedelta(hours=shift)).isoformat()


def build_hl7_version(fhir_rows, mutation_rate=0.15):
    """Copy the FHIR rows, deliberately corrupt ~mutation_rate of them, log ground truth."""
    hl7_rows = []
    ground_truth = []

    for row in fhir_rows:
        hl7_row = dict(row)

        if random.random() < mutation_rate:
            mutation = random.choice(["timing", "coding", "value", "drop"])

            if mutation == "drop":
                ground_truth.append({
                    "observation_id": row["observation_id"],
                    "patient_id": row["patient_id"], "encounter_id": row["encounter_id"],
                    "lab_code": row["lab_code"], "mutation_type": "DROPPED_RECORD",
                    "field_changed": "ENTIRE_ROW", "original_value": "present", "mutated_value": "dropped",
                })
                continue  # row is skipped entirely -- not added to hl7_rows

            elif mutation == "timing":
                original = row["encounter_date"]
                hl7_row["encounter_date"] = shift_date(original)
                ground_truth.append({
                    "observation_id": row["observation_id"],
                    "patient_id": row["patient_id"], "encounter_id": row["encounter_id"],
                    "lab_code": row["lab_code"], "mutation_type": "TIMING_DRIFT",
                    "field_changed": "encounter_date", "original_value": original,
                    "mutated_value": hl7_row["encounter_date"],
                })

            elif mutation == "coding":
                original = row["lab_code"]
                hl7_row["lab_code"] = "LOCAL_" + original
                ground_truth.append({
                    "observation_id": row["observation_id"],
                    "patient_id": row["patient_id"], "encounter_id": row["encounter_id"],
                    "lab_code": original, "mutation_type": "CODING_MISMATCH",
                    "field_changed": "lab_code", "original_value": original,
                    "mutated_value": hl7_row["lab_code"],
                })

            elif mutation == "value":
                try:
                    original = float(row["lab_value"])
                    pct = random.uniform(0.05, 0.15) * random.choice([1, -1])
                    hl7_row["lab_value"] = round(original * (1 + pct), 2)
                    ground_truth.append({
                        "observation_id": row["observation_id"],
                        "patient_id": row["patient_id"], "encounter_id": row["encounter_id"],
                        "lab_code": row["lab_code"], "mutation_type": "VALUE_DISCREPANCY",
                        "field_changed": "lab_value", "original_value": str(original),
                        "mutated_value": str(hl7_row["lab_value"]),
                    })
                except (ValueError, TypeError):
                    pass  # non-numeric value, skip this mutation

        hl7_rows.append(hl7_row)

    return hl7_rows, ground_truth


def write_csv(rows, filepath, fieldnames):
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("extracted_dir", help="Folder containing extracted_*.json files")
    parser.add_argument("--n-patients", type=int, default=50)
    parser.add_argument("--out-dir", default="flat_dataset")
    parser.add_argument("--mutation-rate", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)

    patients = load_patients_with_data(args.extracted_dir, args.n_patients, args.seed)
    print(f"Using {len(patients)} patients")

    all_fhir_rows = []
    for p in patients:
        all_fhir_rows.extend(flatten_patient_fhir(p))

    random.seed(args.seed)  # reset seed so hl7 mutation is reproducible independent of patient sampling
    all_hl7_rows, ground_truth = build_hl7_version(all_fhir_rows, mutation_rate=args.mutation_rate)

    fieldnames = ["observation_id", "patient_id", "patient_name", "dob", "gender", "encounter_id",
                  "encounter_date", "provider", "lab_code", "lab_name", "lab_value", "lab_unit"]
    gt_fieldnames = ["observation_id", "patient_id", "encounter_id", "lab_code", "mutation_type",
                     "field_changed", "original_value", "mutated_value"]

    write_csv(all_fhir_rows, os.path.join(args.out_dir, "patients_fhir.csv"), fieldnames)
    write_csv(all_hl7_rows, os.path.join(args.out_dir, "patients_hl7.csv"), fieldnames)
    write_csv(ground_truth, os.path.join(args.out_dir, "ground_truth_discrepancies.csv"), gt_fieldnames)

    print(f"FHIR rows:  {len(all_fhir_rows)} -> patients_fhir.csv")
    print(f"HL7 rows:   {len(all_hl7_rows)} -> patients_hl7.csv  ({len(all_fhir_rows) - len(all_hl7_rows)} dropped)")
    print(f"Ground truth discrepancies: {len(ground_truth)} -> ground_truth_discrepancies.csv")
