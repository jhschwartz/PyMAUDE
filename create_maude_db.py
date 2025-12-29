import argparse

def main():
    parser = argparse.ArgumentParser(
        description='Create SQLite database from FDA MAUDE data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
        Examples:
            # All data from all time
            python create_maude_db.py --all maude_complete.db
            
            # Specific year range
            python create_maude_db.py --years 2015-2020 maude_2015_2020.db
            
            # Just master event data (core reports only)
            python create_maude_db.py --tables master --all maude_master_only.db
            
            # Patient data for recent years
            python create_maude_db.py --tables patient text --years 2020-2024 patient_narratives.db
            
            # Everything from a single year
            python create_maude_db.py --years 2023 maude_2023.db
        """
    )
    
    # Output database (required)
    parser.add_argument('output_db', help='Path to output SQLite database')
    
    # Year selection (mutually exclusive with --all)
    year_group = parser.add_mutually_exclusive_group(required=True)
    year_group.add_argument('--years', 
                           help='Year range (e.g., "2015-2020" or "2023")')
    year_group.add_argument('--all', action='store_true',
                           help='Download and process all available data (1991-present)')
    
    # Table selection
    parser.add_argument('--tables', nargs='+',
                       choices=['master', 'device', 'patient', 'text', 'problems'],
                       default=['master', 'device', 'patient', 'text'],
                       help='Which tables to include (default: master device patient text)')
    
    # Download option
    parser.add_argument('--download', action='store_true',
                       help='Download files from FDA (otherwise expects files in current directory)')
    
    parser.add_argument('--data-dir', default='./maude_data',
                       help='Directory for downloaded/input files (default: ./maude_data)')
    
    # Processing options
    parser.add_argument('--chunk-size', type=int, default=100000,
                       help='Rows per chunk for memory efficiency (default: 100000)')
    
    parser.add_argument('--verbose', action='store_true',
                       help='Print detailed progress')
    
    args = parser.parse_args()
    
    current_year = 

    # Parse year range
    if args.all:
        years = range(1991, 2025)  # Update end year as needed
    else:
        years = parse_year_range(args.years)
    
    # Build database
    create_database(
        output_db=args.output_db,
        years=years,
        tables=args.tables,
        data_dir=args.data_dir,
        download=args.download,
        chunk_size=args.chunk_size,
        verbose=args.verbose
    )

def parse_year_range(year_str):
    """Parse year string like '2015-2020' or '2023' into list of years"""
    if '-' in year_str:
        start, end = year_str.split('-')
        return range(int(start), int(end) + 1)
    else:
        return [int(year_str)]

def create_database(output_db, years, tables, data_dir, download, chunk_size, verbose):
    """Main database creation logic"""
    
    # Map table names to file prefixes
    table_files = {
        'master': 'mdrfoi',
        'device': 'foidev', 
        'patient': 'patient',
        'text': 'foitext',
        'problems': 'foidevproblem'
    }
    
    import sqlite3
    import pandas as pd
    
    conn = sqlite3.connect(output_db)
    
    for year in years:
        if verbose:
            print(f"\nProcessing year {year}...")
        
        for table in tables:
            file_prefix = table_files[table]
            filename = f"{file_prefix}{year}.txt"
            filepath = f"{data_dir}/{filename}"
            
            if download:
                download_file(year, file_prefix, data_dir, verbose)
            
            if verbose:
                print(f"  Loading {table} data...")
            
            # Process file in chunks
            for i, chunk in enumerate(pd.read_csv(filepath, sep='|', 
                                                  encoding='latin1',
                                                  on_bad_lines='skip',
                                                  chunksize=chunk_size)):
                chunk.to_sql(table, conn, if_exists='append', index=False)
                
                if verbose and i % 10 == 0:
                    print(f"    Chunk {i+1} ({len(chunk)} rows)")
    
    # Create indexes
    if verbose:
        print("\nCreating indexes...")
    
    create_indexes(conn, tables, verbose)
    conn.close()
    
    if verbose:
        print(f"\nDatabase created: {output_db}")

def download_file(year, file_prefix, data_dir, verbose):
    """Download and extract MAUDE file for given year"""
    import requests
    import zipfile
    import os
    
    os.makedirs(data_dir, exist_ok=True)
    
    url = f"https://www.accessdata.fda.gov/MAUDE/ftparea/{file_prefix}{year}.zip"
    zip_path = f"{data_dir}/{file_prefix}{year}.zip"
    
    if verbose:
        print(f"  Downloading {url}...")
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    response = requests.get(url, headers=headers)
    
    with open(zip_path, 'wb') as f:
        f.write(response.content)
    
    # Extract
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(data_dir)

def create_indexes(conn, tables, verbose):
    """Create indexes on commonly queried fields"""
    
    indexes = {
        'master': [
            'CREATE INDEX IF NOT EXISTS idx_master_key ON master(mdr_report_key)',
            'CREATE INDEX IF NOT EXISTS idx_master_date ON master(date_received)'
        ],
        'device': [
            'CREATE INDEX IF NOT EXISTS idx_device_key ON device(mdr_report_key)',
            'CREATE INDEX IF NOT EXISTS idx_device_code ON device(product_code)'
        ],
        'patient': [
            'CREATE INDEX IF NOT EXISTS idx_patient_key ON patient(mdr_report_key)'
        ],
        'text': [
            'CREATE INDEX IF NOT EXISTS idx_text_key ON text(mdr_report_key)'
        ]
    }
    
    for table in tables:
        if table in indexes:
            for index_sql in indexes[table]:
                conn.execute(index_sql)
                if verbose:
                    print(f"  {index_sql}")

if __name__ == '__main__':
    main()