import pandas as pd
import sqlite3
import argparse
import sys

def process_data(input_file, output_db, chunk_size):
    """
    Parse MAUDE text file and convert to SQLite database.
    
    Args:
        input_file: Path to MAUDE pipe-delimited text file
        output_db: Path to output SQLite database
        chunk_size: Number of rows to process per chunk
    """
    try:
        print(f"Creating database: {output_db}")
        print(f"Processing input file: {input_file}")
        
        # Init db connection
        conn = sqlite3.connect(output_db)
        
        # Process in chunks to avoid memory issues
        total_rows = 0
        for i, chunk in enumerate(pd.read_csv(input_file, sep='|', encoding='latin1', 
                                               on_bad_lines='skip', chunksize=chunk_size)):
            
            # Parse and convert the messy MAUDE file input
            chunk.to_sql('mdr_reports', conn, if_exists='append', index=False)
            total_rows += len(chunk)
            print(f"Processed chunk {i+1} ({len(chunk)} rows, {total_rows} total)")
        
        print("Creating indexes...")
        # Add indexes for common queries
        conn.execute('CREATE INDEX idx_product_code ON mdr_reports(product_code)')
        conn.execute('CREATE INDEX idx_date ON mdr_reports(date_received)')
        
        conn.close()
        
        print(f"\nSuccess! Database created with {total_rows} total rows")
        print(f"Database location: {output_db}")
        
    except FileNotFoundError:
        print(f"Error: Input file '{input_file}' not found", file=sys.stderr)
        sys.exit(1)
    except pd.errors.EmptyDataError:
        print(f"Error: Input file '{input_file}' is empty", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error processing data: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    
    parser = argparse.ArgumentParser(description='Parse MAUDE data into SQLite')
    
    # Positional arguments (required)
    parser.add_argument('input_file', help='Path to MAUDE text file')
    parser.add_argument('output_db', help='Path to output SQLite database')
    
    # Optional: specify chunk size
    parser.add_argument('--chunk_size', type=int, default=100000, 
                       help='Number of rows per chunk (default: 100000)')
    
    args = parser.parse_args()
    
    process_data(args.input_file, args.output_db, args.chunk_size)