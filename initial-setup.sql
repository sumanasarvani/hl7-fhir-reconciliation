-- Create a database
CREATE DATABASE IF NOT EXISTS HEALTHCARE_INTEROP_SIMPLE;
USE DATABASE HEALTHCARE_INTEROP_SIMPLE;
USE SCHEMA PUBLIC;

-- Create a warehouse
CREATE WAREHOUSE IF NOT EXISTS INTEROP_WH
  WITH WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

USE WAREHOUSE INTEROP_WH;

-- Create a table (FHIR)
CREATE OR REPLACE TABLE PATIENTS_FHIR (
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

-- Create a table (HL7)
CREATE OR REPLACE TABLE PATIENTS_HL7 (
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

-- Answer key
CREATE OR REPLACE TABLE GROUND_TRUTH_DISCREPANCIES (
    patient_id       STRING,
    encounter_id     STRING,
    lab_code         STRING,
    mutation_type    STRING,
    field_changed    STRING,
    original_value   STRING,
    mutated_value    STRING
);

-- Verify
SHOW TABLES IN HEALTHCARE_INTEROP_SIMPLE.PUBLIC;