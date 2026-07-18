-- Create a unified view
 
USE DATABASE HEALTHCARE_INTEROP_SIMPLE;
USE SCHEMA PUBLIC;
 
CREATE OR REPLACE VIEW DISCREPANCIES AS
 
-- Value mismatches
SELECT
    f.observation_id,
    f.patient_id,
    f.patient_name,
    f.encounter_id,
    f.lab_code,
    f.lab_name,
    'VALUE_DISCREPANCY' AS discrepancy_type,
    f.lab_value::STRING AS fhir_value,
    h.lab_value::STRING AS hl7_value
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.lab_value != h.lab_value
 
UNION ALL
 
-- Coding mismatches
SELECT
    f.observation_id,
    f.patient_id,
    f.patient_name,
    f.encounter_id,
    f.lab_code,
    f.lab_name,
    'CODING_MISMATCH' AS discrepancy_type,
    f.lab_code AS fhir_value,
    h.lab_code AS hl7_value
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.lab_code != h.lab_code
 
UNION ALL
 
-- Timing mismatches
SELECT
    f.observation_id,
    f.patient_id,
    f.patient_name,
    f.encounter_id,
    f.lab_code,
    f.lab_name,
    'TIMING_DRIFT' AS discrepancy_type,
    f.encounter_date::STRING AS fhir_value,
    h.encounter_date::STRING AS hl7_value
FROM PATIENTS_FHIR f
JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE f.encounter_date != h.encounter_date
 
UNION ALL
 
-- Missing records (present in FHIR, dropped from HL7)
SELECT
    f.observation_id,
    f.patient_id,
    f.patient_name,
    f.encounter_id,
    f.lab_code,
    f.lab_name,
    'MISSING_RECORD' AS discrepancy_type,
    'present' AS fhir_value,
    'dropped' AS hl7_value
FROM PATIENTS_FHIR f
LEFT JOIN PATIENTS_HL7 h ON f.observation_id = h.observation_id
WHERE h.observation_id IS NULL;
 
-- Verify
SELECT discrepancy_type, COUNT(*) AS count
FROM DISCREPANCIES
GROUP BY discrepancy_type
ORDER BY count DESC;
 
SELECT COUNT(*) AS total_discrepancies FROM DISCREPANCIES;