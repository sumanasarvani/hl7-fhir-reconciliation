-- Setup and Load
USE DATABASE HEALTHCARE_INTEROP_SIMPLE;
USE SCHEMA PUBLIC;
USE WAREHOUSE INTEROP_WH;

- Create Table schema
CREATE OR REPLACE TABLE PATIENTS_FHIR (
    observation_id  STRING,
    patient_id      STRING,
    patient_name    STRING,
    dob             DATE,
    gender          STRING,
    encounter_id    STRING,
    encounter_date  TIMESTAMP_NTZ,
    provider        STRING,
    lab_code        STRING,
    lab_name        STRING,
    lab_value       FLOAT,
    lab_unit        STRING
);

CREATE OR REPLACE TABLE PATIENTS_HL7 (
    observation_id  STRING,
    patient_id      STRING,
    patient_name    STRING,
    dob             DATE,
    gender          STRING,
    encounter_id    STRING,
    encounter_date  TIMESTAMP_NTZ,
    provider        STRING,
    lab_code        STRING,
    lab_name        STRING,
    lab_value       FLOAT,
    lab_unit        STRING
);

CREATE OR REPLACE TABLE GROUND_TRUTH_DISCREPANCIES (
    observation_id   STRING,
    patient_id       STRING,
    encounter_id     STRING,
    lab_code         STRING,
    mutation_type    STRING,
    field_changed    STRING,
    original_value   STRING,
    mutated_value    STRING
);

-- Create a stage
CREATE STAGE IF NOT EXISTS FLAT_STAGE;

CREATE FILE FORMAT IF NOT EXISTS CSV_FORMAT
    TYPE = CSV
    FIELD_OPTIONALLY_ENCLOSED_BY = '"'
    SKIP_HEADER = 1
    EMPTY_FIELD_AS_NULL = TRUE
    NULL_IF = ('');

-- Upload patients_fhir.csv, patients_hl7.csv, and ground_truth_discrepancies.csv to FLAT_STAGE via Snowsight before running the loads below.

-- Load
COPY INTO PATIENTS_FHIR
    (observation_id, patient_id, patient_name, dob, gender, encounter_id,
     encounter_date, provider, lab_code, lab_name, lab_value, lab_unit)
FROM @FLAT_STAGE/patients_fhir.csv
FILE_FORMAT = (FORMAT_NAME = CSV_FORMAT)
ON_ERROR = 'CONTINUE';

COPY INTO PATIENTS_HL7
    (observation_id, patient_id, patient_name, dob, gender, encounter_id,
     encounter_date, provider, lab_code, lab_name, lab_value, lab_unit)
FROM @FLAT_STAGE/patients_hl7.csv
FILE_FORMAT = (FORMAT_NAME = CSV_FORMAT)
ON_ERROR = 'CONTINUE';

COPY INTO GROUND_TRUTH_DISCREPANCIES
    (observation_id, patient_id, encounter_id, lab_code, mutation_type,
     field_changed, original_value, mutated_value)
FROM @FLAT_STAGE/ground_truth_discrepancies.csv
FILE_FORMAT = (FORMAT_NAME = CSV_FORMAT)
ON_ERROR = 'CONTINUE';

-- Verify the load
SELECT COUNT(*) FROM PATIENTS_FHIR;              -- expect ~2,794
SELECT COUNT(*) FROM PATIENTS_HL7;                -- expect ~2,667
SELECT COUNT(*) FROM GROUND_TRUTH_DISCREPANCIES;  -- expect ~429


-- Reconciliation checks 

-- Value mismatches
SELECT f.patient_id, f.encounter_id, f.lab_code,
       f.lab_value AS fhir_value, h.lab_value AS hl7_value
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.lab_value != h.lab_value;

-- Coding mismatches
SELECT f.patient_id, f.encounter_id, f.lab_name,
       f.lab_code AS fhir_code, h.lab_code AS hl7_code
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.lab_code != h.lab_code;

-- Timing mismatches
SELECT f.patient_id, f.encounter_id, f.lab_code,
       f.encounter_date AS fhir_date, h.encounter_date AS hl7_date
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.encounter_date != h.encounter_date;

-- Missing records (present in FHIR, dropped from HL7)
SELECT f.*
FROM PATIENTS_FHIR f
LEFT JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE h.observation_id IS NULL;