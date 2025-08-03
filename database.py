import asyncpg
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json

load_dotenv()

logger = logging.getLogger("database")

async def create_pool():
    return await asyncpg.create_pool(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432"),
        min_size=5,
        max_size=20
    )

async def get_existing_description(pool, table_name, product_url):
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"""
            SELECT enhanced_description 
            FROM {table_name}
            WHERE product_url = $1 
            AND enhanced_description IS NOT NULL
            ORDER BY scraped_at DESC
            LIMIT 1
            """,
            product_url
        )

async def setup_partitioned_table(pool, table_name, extra_columns=""):
    today = datetime.today().date()
    partition_name = f"{table_name}_{today.strftime('%Y%m%d')}"

    base_columns = [
        "id INT GENERATED ALWAYS AS IDENTITY",
        "store_name TEXT",
        "title TEXT",
        "sku TEXT",
        "description TEXT",
        "currency VARCHAR(3)",
        "original_price DOUBLE PRECISION",
        "sale_price DOUBLE PRECISION",
        "images JSONB NOT NULL DEFAULT '[]'::JSONB",
        "brand TEXT",
        "availability BOOLEAN",
        "category JSONB NOT NULL DEFAULT '[]'::JSONB",
        "product_url TEXT",
        "variants JSONB NOT NULL DEFAULT '[]'::JSONB",
        "attributes JSONB NOT NULL DEFAULT '{}'::JSONB",
        "raw_data JSONB NOT NULL DEFAULT '{}'::JSONB",
        "scraped_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
    ]
    if extra_columns.strip():
        base_columns.append(extra_columns)
    
    base_columns.append("PRIMARY KEY (product_url, scraped_at)")
    
    column_definitions = ",\n        ".join(base_columns)
    logger.info(column_definitions)

    async with pool.acquire() as conn:
        await conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                {column_definitions}
            ) PARTITION BY RANGE (scraped_at);
        """)

        
        await conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {partition_name} PARTITION OF {table_name}
        FOR VALUES FROM ('{today.isoformat()}') TO ('{(today + timedelta(days=1)).isoformat()}');
        """)
        
        await conn.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_{table_name}_url 
        ON {table_name} (product_url);
        
        CREATE INDEX IF NOT EXISTS idx_{table_name}_scraped 
        ON {table_name} (scraped_at);
        """)
    
    logger.info(f"Ensured partition exists: {partition_name}")
    return partition_name

async def record_exists(pool, table_name, product_url):
    today = datetime.today().date()
    partition_name = f"{table_name}_{today.strftime('%Y%m%d')}"
    
    async with pool.acquire() as conn:
        return await conn.fetchval(
            f"SELECT 1 FROM {partition_name} WHERE product_url = $1",
            product_url
        )

async def insert_products(pool, table_name, products):
    today = datetime.today().date()
    partition_name = f"{table_name}_{today.strftime('%Y%m%d')}"
    inserted_count = 0
    
    async with pool.acquire() as conn:
        for product in products:    
            if isinstance(availability, str):
                truthy = ['true', 'yes', 'available', '1', 'in stock']
                falsy = ['false', 'no', '0', 'not available', 'out of stock', 'unavailable']
                cleaned = availability.lower().strip()
                
                if cleaned in truthy:
                    availability = True
                elif cleaned in falsy:
                    availability = False
                else:
                    availability = None 
            elif isinstance(availability, (bool, type(None))):
                pass
            else:
                availability = None
            
            base_values = [
                product.get('store_name'),
                product.get('title'),
                product.get('sku'),
                product.get('description'),
                product.get('currency'),
                float(product.get('original_price')) if product.get('original_price') is not None else None,
                float(product.get('sale_price')) if product.get('sale_price') is not None else None,
                json.dumps(product.get('images') or []),     
                product.get('brand'),
                availability,
                json.dumps(product.get('category') or []), 
                product.get('product_url'),
                json.dumps(product.get('variants') or []), 
                json.dumps(product.get('attributes') or {}),
                json.dumps(product.get('raw_data') or {})
            ]
            
            enhanced_description = product.get('enhanced_description')
            if enhanced_description is not None:
                columns = [
                    'store_name', 'title', 'sku', 'description', 'currency', 
                    'original_price', 'sale_price', 'images', 'brand', 'availability',
                    'category', 'product_url', 'variants', 'attributes', 'raw_data',
                    'enhanced_description'
                ]
                values = [*base_values, enhanced_description]
                placeholders = ", ".join([f"${i}" for i in range(1, 17)])  
            else:
                columns = [
                    'store_name', 'title', 'sku', 'description', 'currency', 
                    'original_price', 'sale_price', 'images', 'brand', 'availability',
                    'category', 'product_url', 'variants', 'attributes', 'raw_data'
                ]
                values = base_values
                placeholders = ", ".join([f"${i}" for i in range(1, 16)])  
            
            try:
                await conn.execute(
                    f"""
                    INSERT INTO {partition_name} ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT (product_url, scraped_at) DO NOTHING
                    """,
                    *values
                )
                inserted_count += 1
            except Exception as e:
                logger.error(f"Error inserting product: {e}", exc_info=True)
        
        return inserted_count