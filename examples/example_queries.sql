-- MAUDE Database Example SQL Queries
--
-- This file contains ready-to-use SQL queries for common MAUDE research tasks.
-- Copy and paste these queries into your SQLite tool (DB Browser, DBeaver, etc.)
--
-- Tips:
-- - Modify the search terms (e.g., '%pacemaker%') for your research
-- - Use LIMIT to preview results before running full queries
-- - Remember: device/text tables use UPPERCASE column names
--
-- Copyright (C) 2024 Jacob Schwartz, University of Michigan Medical School

-- =============================================================================
-- BASIC QUERIES - Getting Started
-- =============================================================================

-- Count total device reports in database
SELECT COUNT(*) as total_reports
FROM device;

-- Count reports for a specific device type (change 'pacemaker' to your device)
SELECT COUNT(*) as pacemaker_reports
FROM device
WHERE GENERIC_NAME LIKE '%pacemaker%';

-- Show all unique device types (generic names)
SELECT DISTINCT GENERIC_NAME
FROM device
ORDER BY GENERIC_NAME;

-- Preview first 10 device records
SELECT *
FROM device
LIMIT 10;

-- Get column names and sample data from device table
SELECT *
FROM device
LIMIT 1;


-- =============================================================================
-- SEARCHING AND FILTERING
-- =============================================================================

-- Find all catheter devices
SELECT
    MDR_REPORT_KEY,
    GENERIC_NAME,
    BRAND_NAME,
    MANUFACTURER_D_NAME,
    DATE_RECEIVED
FROM device
WHERE GENERIC_NAME LIKE '%catheter%'
LIMIT 100;

-- Search by brand name
SELECT *
FROM device
WHERE BRAND_NAME LIKE '%Medtronic%'
LIMIT 50;

-- Search by manufacturer
SELECT
    GENERIC_NAME,
    BRAND_NAME,
    COUNT(*) as report_count
FROM device
WHERE MANUFACTURER_D_NAME LIKE '%Boston Scientific%'
GROUP BY GENERIC_NAME, BRAND_NAME
ORDER BY report_count DESC;

-- Filter by product code
SELECT *
FROM device
WHERE DEVICE_REPORT_PRODUCT_CODE = 'NIQ'
LIMIT 100;

-- Filter by date range
SELECT *
FROM device
WHERE
    DATE_RECEIVED >= '2020-01-01'
    AND DATE_RECEIVED <= '2020-12-31'
LIMIT 100;


-- =============================================================================
-- AGGREGATION AND COUNTING
-- =============================================================================

-- Count reports by device type (top 20)
SELECT
    GENERIC_NAME,
    COUNT(*) as report_count
FROM device
GROUP BY GENERIC_NAME
ORDER BY report_count DESC
LIMIT 20;

-- Count reports by manufacturer
SELECT
    MANUFACTURER_D_NAME,
    COUNT(*) as report_count
FROM device
GROUP BY MANUFACTURER_D_NAME
ORDER BY report_count DESC
LIMIT 20;

-- Count reports by year
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as report_count
FROM device
GROUP BY year
ORDER BY year;

-- Reports by year for specific device type
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%defibrillator%'
GROUP BY year
ORDER BY year;

-- Count unique brands for a device type
SELECT COUNT(DISTINCT BRAND_NAME) as unique_brands
FROM device
WHERE GENERIC_NAME LIKE '%stent%';


-- =============================================================================
-- JOINING DEVICE AND TEXT TABLES
-- =============================================================================

-- Get device information with event narratives
SELECT
    d.MDR_REPORT_KEY,
    d.GENERIC_NAME,
    d.BRAND_NAME,
    d.MANUFACTURER_D_NAME,
    d.DATE_RECEIVED,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE d.GENERIC_NAME LIKE '%thrombectomy%'
LIMIT 50;

-- Count how many device reports have narratives
SELECT
    'Devices' as table_name,
    COUNT(*) as count
FROM device

UNION ALL

SELECT
    'With narratives' as table_name,
    COUNT(DISTINCT d.MDR_REPORT_KEY) as count
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY;

-- Find devices where narrative mentions specific keywords
SELECT
    d.GENERIC_NAME,
    d.BRAND_NAME,
    d.MDR_REPORT_KEY,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE
    d.GENERIC_NAME LIKE '%catheter%'
    AND (
        t.FOI_TEXT LIKE '%fracture%'
        OR t.FOI_TEXT LIKE '%break%'
        OR t.FOI_TEXT LIKE '%failure%'
    )
LIMIT 25;


-- =============================================================================
-- SPECIFIC RESEARCH QUERIES
-- =============================================================================

-- Thrombectomy device analysis
SELECT
    BRAND_NAME,
    MANUFACTURER_D_NAME,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%thrombectomy%'
GROUP BY BRAND_NAME, MANUFACTURER_D_NAME
ORDER BY report_count DESC;

-- Insulin pump reports by year
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%insulin%pump%'
GROUP BY year
ORDER BY year;

-- Pacemaker reports from specific manufacturer
SELECT
    BRAND_NAME,
    MODEL_NUMBER,
    COUNT(*) as report_count
FROM device
WHERE
    GENERIC_NAME LIKE '%pacemaker%'
    AND MANUFACTURER_D_NAME LIKE '%Medtronic%'
GROUP BY BRAND_NAME, MODEL_NUMBER
ORDER BY report_count DESC
LIMIT 20;

-- Recent stent reports with narratives
SELECT
    d.DATE_RECEIVED,
    d.BRAND_NAME,
    d.MANUFACTURER_D_NAME,
    t.FOI_TEXT
FROM device d
JOIN text t ON d.MDR_REPORT_KEY = t.MDR_REPORT_KEY
WHERE
    d.GENERIC_NAME LIKE '%stent%'
    AND d.DATE_RECEIVED >= '2023-01-01'
ORDER BY d.DATE_RECEIVED DESC
LIMIT 50;


-- =============================================================================
-- QUALITY CHECKS AND EXPLORATION
-- =============================================================================

-- Check for missing brand names
SELECT
    COUNT(*) as total_records,
    SUM(CASE WHEN BRAND_NAME IS NULL OR BRAND_NAME = '' THEN 1 ELSE 0 END) as missing_brand,
    SUM(CASE WHEN MANUFACTURER_D_NAME IS NULL OR MANUFACTURER_D_NAME = '' THEN 1 ELSE 0 END) as missing_manufacturer
FROM device;

-- Find records with specific model number
SELECT *
FROM device
WHERE MODEL_NUMBER = 'YOUR_MODEL_NUMBER'
LIMIT 100;

-- Sample random reports for a device type (for qualitative review)
SELECT *
FROM device
WHERE GENERIC_NAME LIKE '%defibrillator%'
ORDER BY RANDOM()
LIMIT 20;

-- Get date range of data in database
SELECT
    MIN(DATE_RECEIVED) as earliest_report,
    MAX(DATE_RECEIVED) as latest_report,
    COUNT(*) as total_reports
FROM device;


-- =============================================================================
-- ADVANCED QUERIES
-- =============================================================================

-- Top brands by year for a device type
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    BRAND_NAME,
    COUNT(*) as report_count
FROM device
WHERE GENERIC_NAME LIKE '%pacemaker%'
GROUP BY year, BRAND_NAME
ORDER BY year DESC, report_count DESC;

-- Manufacturers with most diverse product line (most generic names)
SELECT
    MANUFACTURER_D_NAME,
    COUNT(DISTINCT GENERIC_NAME) as unique_device_types,
    COUNT(*) as total_reports
FROM device
GROUP BY MANUFACTURER_D_NAME
ORDER BY unique_device_types DESC
LIMIT 20;

-- Compare report volumes between two manufacturers
SELECT
    MANUFACTURER_D_NAME,
    COUNT(*) as report_count
FROM device
WHERE
    GENERIC_NAME LIKE '%catheter%'
    AND (
        MANUFACTURER_D_NAME LIKE '%Medtronic%'
        OR MANUFACTURER_D_NAME LIKE '%Boston Scientific%'
    )
GROUP BY MANUFACTURER_D_NAME;

-- Monthly trend for specific device
SELECT
    strftime('%Y-%m', DATE_RECEIVED) as month,
    COUNT(*) as report_count
FROM device
WHERE
    GENERIC_NAME LIKE '%insulin pump%'
    AND DATE_RECEIVED >= '2020-01-01'
GROUP BY month
ORDER BY month;

-- Find duplicate reports (same device, same day)
SELECT
    BRAND_NAME,
    MODEL_NUMBER,
    DATE_RECEIVED,
    COUNT(*) as duplicate_count
FROM device
WHERE BRAND_NAME IS NOT NULL AND MODEL_NUMBER IS NOT NULL
GROUP BY BRAND_NAME, MODEL_NUMBER, DATE_RECEIVED
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC
LIMIT 50;


-- =============================================================================
-- EXPORT-READY QUERIES
-- =============================================================================
-- These queries are designed to be exported to CSV for further analysis

-- Device report summary for export
SELECT
    MDR_REPORT_KEY,
    GENERIC_NAME,
    BRAND_NAME,
    MANUFACTURER_D_NAME,
    MODEL_NUMBER,
    CATALOG_NUMBER,
    LOT_NUMBER,
    DEVICE_REPORT_PRODUCT_CODE,
    DATE_RECEIVED,
    MANUFACTURER_D_CITY,
    MANUFACTURER_D_STATE_CODE,
    MANUFACTURER_D_COUNTRY_CODE
FROM device
WHERE GENERIC_NAME LIKE '%YOUR_DEVICE_TYPE%'
ORDER BY DATE_RECEIVED DESC;

-- Year-by-year summary for specific device
SELECT
    strftime('%Y', DATE_RECEIVED) as year,
    COUNT(*) as total_reports,
    COUNT(DISTINCT BRAND_NAME) as unique_brands,
    COUNT(DISTINCT MANUFACTURER_D_NAME) as unique_manufacturers
FROM device
WHERE GENERIC_NAME LIKE '%YOUR_DEVICE_TYPE%'
GROUP BY year
ORDER BY year;

-- Manufacturer comparison table
SELECT
    MANUFACTURER_D_NAME,
    COUNT(*) as total_reports,
    COUNT(DISTINCT BRAND_NAME) as unique_brands,
    MIN(DATE_RECEIVED) as first_report,
    MAX(DATE_RECEIVED) as last_report
FROM device
WHERE GENERIC_NAME LIKE '%YOUR_DEVICE_TYPE%'
GROUP BY MANUFACTURER_D_NAME
ORDER BY total_reports DESC;


-- =============================================================================
-- NOTES AND TIPS
-- =============================================================================

-- Remember to:
-- 1. Replace '%YOUR_DEVICE_TYPE%' with your actual search term
-- 2. Adjust date ranges for your research period
-- 3. Use LIMIT when exploring to avoid loading too much data
-- 4. Export results to CSV for analysis in Excel, R, Python, etc.
--
-- Column name casing:
-- - device table: UPPERCASE (e.g., GENERIC_NAME, BRAND_NAME)
-- - text table: UPPERCASE (e.g., FOI_TEXT, MDR_REPORT_KEY)
-- - patient table: lowercase (e.g., mdr_report_key, date_received)
--
-- For more help, see:
-- - docs/sqlite_guide.md - Detailed SQLite usage guide
-- - docs/maude_overview.md - Understanding MAUDE database structure
-- - docs/research_guide.md - Research best practices
