# query_device(...): exact-match search on one or more device fields.
angiojet = db.query_device(brand_name='ANGIOJET', start_date='2015-01-01')

# search_by_device_names(...): case-insensitive substring search over the brand,
# generic, and manufacturer name fields, with user-specified boolean logic.
term_or     = db.search_by_device_names(['argon', 'cleaner'])
term_and_or = db.search_by_device_names([['venous', 'thrombectomy'], ['vein', 'angiojet']])

# query(...): arbitrary SQL for anything outside the two functions above.
reports_per_year = db.query(
    "SELECT year(DATE_RECEIVED) AS year, COUNT(*) AS n FROM master GROUP BY year ORDER BY year"
)

# Attach patient outcomes, problem codes, and narratives, then filter on any of them.
results = db.enrich_with_patient_data(term_and_or)
results = db.enrich_with_device_problems(results)
narratives = db.get_narratives(results['MDR_REPORT_KEY'])
deaths = db.filter_by_outcome(results, outcome=['D', 'L'])

# Results remain pandas DataFrames throughout, ready for analysis or export.
trends = db.get_trends_by_year(results)
trends.to_csv('venous_thrombectomy_trends.csv', index=False)
db.close()