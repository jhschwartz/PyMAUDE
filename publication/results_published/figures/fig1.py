from pymaude import MaudeDatabase

# add_years(...) downloads, repairs malformed lines, and loads all six MAUDE
# tables into a local DuckDB database for a user-specified range of years.
db = MaudeDatabase(db_path='./maude.duckdb', data_dir='./maude_data', memory_limit='4GB')
db.add_years(years='2015-2025', download=True)

# update(...) re-downloads every currently-loaded source file and reloads
# only those whose checksum has changed since the last build.
db.update(force_download=True)

# archive(...) writes a checksum manifest alongside a citable snapshot of the
# database and its raw source files, for deposit in a repository such as Zenodo.
db.archive(output_dir='./maude_archive', include_raw=True, compress=True)

