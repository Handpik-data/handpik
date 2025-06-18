import os
import json
import psycopg2
from psycopg2 import sql
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST"),
    "port": os.getenv("DB_PORT", "5432")
}

if not all(DB_CONFIG.values()):
    missing = [k for k, v in DB_CONFIG.items() if not v]
    raise EnvironmentError(f"Missing database configuration: {', '.join(missing)}")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_DIR = os.path.join(SCRIPT_DIR, 'jsondata')

def create_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.autocommit = False
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def create_table(conn):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    table_name = f"product_{timestamp}"

    create_query = sql.SQL("""
    CREATE TABLE {table} (
        id SERIAL PRIMARY KEY,
        store_name TEXT,
        title TEXT,
        sku TEXT,
        description TEXT,
        currency VARCHAR(3),
        original_price TEXT,
        sale_price TEXT,
        images JSONB NOT NULL DEFAULT '[]'::JSONB,
        brand TEXT,
        availability BOOLEAN,
        category TEXT,
        product_url TEXT,
        variants JSONB NOT NULL DEFAULT '[]'::JSONB,
        attributes JSONB NOT NULL DEFAULT '{{}}'::JSONB,
        raw_data JSONB NOT NULL DEFAULT '{{}}'::JSONB,
        scraped_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    )
    """).format(table=sql.Identifier(table_name))
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(create_query)
            print(f"Created new table: {table_name}")
            return table_name
    except Exception as e:
        print(f"Error creating table: {e}")
        conn.rollback()
        return None

def process_availability(availability):
    if availability is None:
        return None
    if isinstance(availability, bool):
        return availability
    if isinstance(availability, str):
        return availability.lower() in ['true', 'yes', 'available', '1']
    return bool(availability)

def insert_product(conn, table_name, product):
    query = sql.SQL("""
    INSERT INTO {table} (
        store_name, title, sku, description, currency, 
        original_price, sale_price, images, brand, availability,
        category, product_url, variants, attributes, raw_data
    ) VALUES (
        %s, %s, %s, %s, %s, 
        %s, %s, %s::jsonb, %s, %s,
        %s, %s, %s::jsonb, %s::jsonb, %s::jsonb
    )
    """).format(table=sql.Identifier(table_name))
    
    try:
        original_price = product.get('original_price')
        sale_price = product.get('sale_price')
        
        availability = process_availability(product.get('availability'))
        
        with conn.cursor() as cursor:
            cursor.execute(query, (
                product.get('store_name'),
                product.get('title'),
                product.get('sku'),
                product.get('description'),
                product.get('currency'),
                original_price,
                sale_price,
                json.dumps(product.get('images', [])),
                product.get('brand'),
                availability,
                product.get('category'),
                product.get('product_url'),
                json.dumps(product.get('variants', [])),
                json.dumps(product.get('attributes', {})),
                json.dumps(product.get('raw_data', {}))
            ))
        return True
    except Exception as e:
        print(f"Error inserting product: {e}")
        return False

def process_json_files():
    conn = create_connection()
    if not conn:
        return

    table_name = create_table(conn)
    if not table_name:
        conn.close()
        return
    
    processed = 0
    errors = 0
    start_time = datetime.now()
    
    try:
        if not os.path.exists(JSON_DIR):
            print(f"JSON directory not found at: {JSON_DIR}")
            return
            
        for filename in os.listdir(JSON_DIR):
            if filename.endswith('.json'):
                filepath = os.path.join(JSON_DIR, filename)
                print(f"Processing {filename}...")
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        products = json.load(f)
                    
                    file_count = 0
                    for product in products:
                        if insert_product(conn, table_name, product):
                            processed += 1
                            file_count += 1
                        else:
                            errors += 1
                    print(f"  Inserted {file_count} products from {filename}")
                    
                except json.JSONDecodeError:
                    print(f"  ERROR: Invalid JSON in {filename}")
                    errors += 1
                except Exception as e:
                    print(f"  ERROR processing {filename}: {e}")
                    errors += 1
        
        conn.commit()
        print(f"\nProcess completed in {datetime.now() - start_time}")
        print(f"Created table: {table_name}")
        print(f"Total products processed: {processed}")
        print(f"Total errors: {errors}")
        
    except Exception as e:
        conn.rollback()
        print(f"Processing failed: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    process_json_files()