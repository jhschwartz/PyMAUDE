import pandas as pd
import sqlite3
import os
from datetime import datetime
import requests
import zipfile


class MaudeDatabase:
    """
    Interface to FDA MAUDE database - handles download, parsing, and querying.
    
    Usage:
        # Connect to existing database
        db = MaudeDatabase('maude.db')
        
        # Add data
        db.add_years('2015-2024', tables=['master', 'device'], download=True)
        
        # Query
        results = db.query_device(device_name='thrombectomy')
        
        # Update with latest
        db.update()
    """
    
    base_url = "https://www.accessdata.fda.gov/MAUDE/ftparea"
    
    table_files = {
        'master': 'mdrfoi',
        'device': 'foidev',
        'patient': 'patient',
        'text': 'foitext',
        'problems': 'foidevproblem'
    }
    

    def __init__(self, db_path, verbose=True):
        """
        Initialize connection to MAUDE database.
        Creates new database if doesn't exist, connects to existing if it does.
        
        Args:
            db_path: Path to SQLite database file
            verbose: Whether to print progress messages
        """
        self.db_path = db_path
        self.verbose = verbose
        self.conn = sqlite3.connect(self.db_path)
    

    def __enter__(self):
        """Context manager entry - allows 'with MaudeDatabase() as db:' syntax"""
        return self
    

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - clean up connection"""
        self.conn.close()
    

    def add_years(self, years, tables=None, download=False, strict=False, chunk_size=100000):
        """
        Add MAUDE data for specified years to database.
        
        Args:
            years: Year or years to add. Can be:
                   - Single int: 2024
                   - List: [2020, 2021, 2022]
                   - String range: '2015-2024'
                   - String: 'all', 'latest'
            tables: List of tables to include (default: all main tables)
            download: Whether to download files from FDA
            strict: If True, raise error on missing files. If False, skip with warning.
            chunk_size: Rows to process at once (for memory efficiency)
        """
        years = self._parse_year_range(years)
        
        if tables is None: 
            tables = ['master', 'device', 'patient', 'text']
        
        for year in years:
            if self.verbose:
                print(f'\nProcessing year {year}...')                

            for table in tables:
                file_prefix = self.table_files[table]
                
                if download:
                    if not self._download_file(year, file_prefix):
                        if strict:
                            raise FileNotFoundError(f'Could not download {file_prefix}{year}')
                        if self.verbose:
                            print(f'  Skipping {table} {year} - download failed')
                        continue
                
                path = self._make_file_path(table, year)
                if not path:
                    if strict:
                        raise FileNotFoundError(f'No file found for table={table}, year={year}')
                    if self.verbose:
                        print(f'  Skipping {table} {year} - file not found')
                    continue
                
                if self.verbose:
                    print(f'  Loading {table}...')
                
                self._process_file(path, table, chunk_size)
        
        self._create_indexes(tables)
        
        if self.verbose:
            print('\nDatabase update complete')


    def _parse_year_range(self, year_str):
        """
        Convert year string to list of year integers.
        
        Args:
            year_str: String like '2015-2024', 'all', 'latest', or single year '2024'
        
        Returns:
            List of year integers
        """
        if isinstance(year_str, int):
            return [year_str]
        
        if isinstance(year_str, list):
            return year_str
        
        if year_str == 'all':
            return range(1991, datetime.now().year)
        elif year_str == 'latest':
            return [datetime.now().year - 1]
        elif '-' in year_str:
            start, end = year_str.split('-')
            return range(int(start), int(end) + 1)

        return [int(year_str)]

    
    def _make_file_path(self, table, year):
        """
        Create a path for the MAUDE datafile of a table type and year, returning only if it exists.
        Tries both lowercase and uppercase table path prefix, e.g. "device2000.txt" and "DEVICE2000.txt"
        
        Returns:
            path if it exists
            Otherwise returns False
        """
        table_name = self.table_files[table]
        path = f"./maude_data/{table_name}{year}.txt"
        if os.path.exists(path):
            return path 
        
        path = f"./maude_data/{table_name.upper()}{year}.txt"
        if os.path.exists(path):
            return path
        
        return False


    def _download_file(self, year, file_prefix, data_dir='./maude_data'):
        """
        Download and extract a MAUDE file from FDA.
        
        Args:
            year: Year to download
            file_prefix: File type prefix (e.g., 'mdrfoi', 'foidev')
            data_dir: Directory to save files
        
        Returns:
            True if successful, False otherwise
        """
        os.makedirs(data_dir, exist_ok=True)
        
        url = f"{self.base_url}/{file_prefix}{year}.zip"
        zip_path = f"{data_dir}/{file_prefix}{year}.zip"
        
        if os.path.exists(zip_path):
            if self.verbose:
                print(f'  Using cached {file_prefix}{year}.zip')
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(data_dir)
                return True
            except:
                os.remove(zip_path)
        
        try:
            if self.verbose:
                print(f'  Downloading {file_prefix}{year}.zip...')
            
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            with open(zip_path, 'wb') as f:
                f.write(response.content)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(data_dir)
            
            return True
            
        except Exception as e:
            if self.verbose:
                print(f'  Error downloading {year}: {e}')
            return False


    def _check_file_exists(self, year, file_prefix):
        """
        Check if a file exists on FDA server without downloading.
        
        Args:
            year: Year to check
            file_prefix: File type to check
        
        Returns:
            True if file exists (status 200), False otherwise
        """
        url = f"{self.base_url}/{file_prefix}{year}.zip"
        
        try:
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.head(url, headers=headers, timeout=5)
            return response.status_code == 200
        except:
            return False


    def _process_file(self, filepath, table_name, chunk_size):
        """
        Read MAUDE text file and insert into SQLite database.
        
        Args:
            filepath: Path to pipe-delimited text file
            table_name: Name of table to insert into
            chunk_size: Number of rows to process at once
        """
        total_rows = 0
        
        for i, chunk in enumerate(pd.read_csv(
            filepath, 
            sep='|', 
            encoding='latin1',
            on_bad_lines='skip',
            chunksize=chunk_size,
            low_memory=False
        )):
            chunk.to_sql(table_name, self.conn, if_exists='append', index=False)
            total_rows += len(chunk)
            
            if self.verbose and i % 10 == 0 and i > 0:
                print(f'    Processed {total_rows:,} rows...')
        
        if self.verbose:
            print(f'    Total: {total_rows:,} rows')


    def _create_indexes(self, tables):
        """
        Create indexes on commonly queried fields for performance.
        
        Args:
            tables: List of tables that were added
        """
        if self.verbose:
            print('\nCreating indexes...')
        
        if 'master' in tables:
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_master_key ON master(mdr_report_key)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_master_date ON master(date_received)')
        
        if 'device' in tables:
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_device_key ON device(mdr_report_key)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_device_code ON device(product_code)')
        
        if 'patient' in tables:
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_patient_key ON patient(mdr_report_key)')
        
        if 'text' in tables:
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_text_key ON text(mdr_report_key)')
        
        self.conn.commit()


    def update(self):
        """
        Add the most recent available year to database.
        Checks what years are already in database and adds newest if missing.
        """
        latest = self._get_latest_available_year()
        existing = self._get_years_in_db()
        
        if latest not in existing:
            if self.verbose:
                print(f'Updating with {latest} data...')
            self.add_years([latest], download=True)
        else:
            if self.verbose:
                print('Database is up to date')


    def _get_latest_available_year(self):
        """
        Find the most recent year available on FDA server.
        
        Returns:
            Most recent year as integer
        """
        current_year = datetime.now().year
        
        for year in range(current_year, 1990, -1):
            if self._check_file_exists(year, 'mdrfoi'):
                return year
        
        return current_year - 1


    def _get_years_in_db(self):
        """
        Get list of years currently in the database.
        
        Returns:
            List of years (as integers)
        """
        try:
            df = pd.read_sql_query(
                "SELECT DISTINCT strftime('%Y', date_received) as year FROM master",
                self.conn
            )
            return [int(y) for y in df['year'].tolist() if y]
        except:
            return []


    def query(self, sql, params=None):
        """
        Execute raw SQL query and return results as DataFrame.
        
        Args:
            sql: SQL query string
            params: Optional parameters for query (for safety)
        
        Returns:
            pandas DataFrame with results
        """
        return pd.read_sql_query(sql, self.conn, params=params)


    def query_device(self, device_name=None, product_code=None, 
                     start_date=None, end_date=None):
        """
        Query device events with optional filters.
        
        Args:
            device_name: Filter by generic_name or brand_name (partial match)
            product_code: Filter by exact product code
            start_date: Only events on/after this date
            end_date: Only events on/before this date
        
        Returns:
            DataFrame with matching records from master + device tables
        """
        conditions = []
        params = {}
        
        if device_name:
            conditions.append("(d.generic_name LIKE :device OR d.brand_name LIKE :device)")
            params['device'] = f'%{device_name}%'
        
        if product_code:
            conditions.append("d.product_code = :code")
            params['code'] = product_code
        
        if start_date:
            conditions.append("m.date_received >= :start")
            params['start'] = start_date
        
        if end_date:
            conditions.append("m.date_received <= :end")
            params['end'] = end_date
        
        where = " AND ".join(conditions) if conditions else "1=1"
        
        sql = f"""
            SELECT m.*, d.*
            FROM master m
            JOIN device d ON m.mdr_report_key = d.mdr_report_key
            WHERE {where}
        """
        
        return pd.read_sql_query(sql, self.conn, params=params)


    def get_trends_by_year(self, product_code=None, device_name=None):
        """
        Get yearly event counts and breakdown by event type.
        
        Args:
            product_code: Optional filter by product code
            device_name: Optional filter by device name
        
        Returns:
            DataFrame with columns: year, event_count, deaths, injuries, malfunctions
        """
        condition = "1=1"
        params = {}
        
        if product_code:
            condition = "d.product_code = :code"
            params['code'] = product_code
        elif device_name:
            condition = "(d.generic_name LIKE :name OR d.brand_name LIKE :name)"
            params['name'] = f'%{device_name}%'
        
        sql = f"""
            SELECT 
                strftime('%Y', m.date_received) as year,
                COUNT(*) as event_count,
                SUM(CASE WHEN m.event_type LIKE '%Death%' THEN 1 ELSE 0 END) as deaths,
                SUM(CASE WHEN m.event_type LIKE '%Injury%' THEN 1 ELSE 0 END) as injuries,
                SUM(CASE WHEN m.event_type LIKE '%Malfunction%' THEN 1 ELSE 0 END) as malfunctions
            FROM master m
            JOIN device d ON m.mdr_report_key = d.mdr_report_key
            WHERE {condition}
            GROUP BY year
            ORDER BY year
        """
        
        return pd.read_sql_query(sql, self.conn, params=params)


    def get_narratives(self, mdr_report_keys):
        """
        Get text narratives for specific report keys.
        
        Args:
            mdr_report_keys: List of MDR report keys
        
        Returns:
            DataFrame with mdr_report_key and narrative text
        """
        placeholders = ','.join('?' * len(mdr_report_keys))
        
        sql = f"""
            SELECT mdr_report_key, mdr_text
            FROM text
            WHERE mdr_report_key IN ({placeholders})
        """
        
        return pd.read_sql_query(sql, self.conn, params=mdr_report_keys)


    def export_subset(self, output_file, **filters):
        """
        Export filtered data to CSV file.
        
        Args:
            output_file: Path for output CSV
            **filters: Keyword arguments passed to query_device()
        """
        df = self.query_device(**filters)
        df.to_csv(output_file, index=False)
        
        if self.verbose:
            print(f'Exported {len(df):,} records to {output_file}')


    def info(self):
        """
        Print summary statistics about the database.
        Displays: tables present, record counts, date range
        """
        print(f"\nDatabase: {self.db_path}")
        print("=" * 60)
        
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'",
            self.conn
        )['name'].tolist()
        
        if not tables:
            print("Database is empty")
            return
        
        for table in tables:
            count = pd.read_sql_query(
                f"SELECT COUNT(*) as count FROM {table}",
                self.conn
            )['count'][0]
            print(f"{table:15} {count:,} records")
        
        if 'master' in tables:
            date_info = pd.read_sql_query(
                "SELECT MIN(date_received) as first, MAX(date_received) as last FROM master",
                self.conn
            ).iloc[0]
            print(f"\nDate range: {date_info['first']} to {date_info['last']}")
        
        db_size = os.path.getsize(self.db_path) / (1024**3)
        print(f"Database size: {db_size:.2f} GB")
    

    def close(self):
        """Close database connection."""
        self.conn.close()