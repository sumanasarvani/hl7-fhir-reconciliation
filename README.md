# HL7 / FHIR Interoperability Reconciliation

A pipeline and dashboard that reconciles legacy **HL7 v2** healthcare data feeds against modern **FHIR** feeds for the same patients — detecting mismatches in lab results, coding, and timing, with a natural-language query layer built on **Snowflake Cortex Analyst**.

---

## The problem

Hospitals frequently run two systems side by side: an older one speaking **HL7 v2** (the long-standing standard for admissions, lab results, and clinical messaging) and a newer one speaking **FHIR** (the modern standard most current health-tech is built on). These two feeds don't always agree — timestamps drift between systems, lab codes get mapped inconsistently, values get corrupted in translation, and records occasionally never make it across at all. Reconciling legacy and modern interoperability standards is a real, recurring problem in healthcare IT — not a hypothetical one.

## What this project does

1. **Generates realistic synthetic patient data** (demographics, encounters, lab results) using [Synthea](https://github.com/synthetichealth/synthea)
2. **Produces two versions of the same patients** — one styled as a FHIR feed, one styled as an HL7 feed — with the HL7 side deliberately containing realistic data-quality issues: dropped records, timing drift, coding mismatches, and value discrepancies
3. **Loads both into Snowflake** and automatically detects every discrepancy between them via a reconciliation view
4. **Exposes a natural-language query layer** via Snowflake Cortex Analyst — ask a plain-English question, get back real generated SQL and results
5. **Displays it all in an interactive Streamlit dashboard** with four screens

---
## Run instructions

### 1. Generate synthetic patient data

Requires Java. From the Synthea repo:
```bash
./run_synthea -p 100
```
This produces FHIR JSON bundles in `output/fhir/`.

### 2. Extract and flatten locally

```bash
pip install python-dateutil --break-system-packages
python3 batch_extract.py output/fhir --out-dir extracted --years 3 --reference-date 2026-07-17
python3 build_flat_dataset.py extracted --n-patients 50 --out-dir flat_dataset --seed 42
```
This produces three CSVs in `flat_dataset/`: `patients_fhir.csv`, `patients_hl7.csv`, `ground_truth_discrepancies.csv`.

*(A small 25-row excerpt of each is included in `sample_data/` for quick reference without running the pipeline.)*

### 3. Set up Snowflake

In Snowsight, run in order:
1. **`initial-setup.sql`** — creates the database, schema, warehouse, and tables
2. **`setup-load.sql`** — creates the stage and file format, loads the three CSVs (upload them to the `FLAT_STAGE` stage first via Snowsight's file upload UI), and includes the reconciliation validation queries
3. **`unified_view.sql`** — creates the `DISCREPANCIES` view that combines all four discrepancy checks into one queryable result

### 4. Set up Cortex Analyst

1. Upload `semantic-model.yaml` to a stage (e.g. `SEMANTIC_STAGE`)
2. In Snowsight: **AI & ML → Cortex Analyst → Create new → Upload YAML file**
3. Test it with a question like *"How many discrepancies are there of each type?"*

### 5. Deploy the Streamlit app

1. In Snowsight: **Projects → Streamlit → + Streamlit App**
2. Paste in the contents of `streamlit_app.py`
3. Confirm the `DATABASE`, `SCHEMA`, `STAGE`, and `SEMANTIC_MODEL_FILE` constants near the top of the file match your setup
4. Click **Run**
