import asyncio
import os
import json
import logging
from datetime import datetime
from database import create_pool, setup_partitioned_table, insert_products
import logging
from utils.LoggerConstants import SQL_LOGGER
import global_constants

logger = logging.getLogger(SQL_LOGGER)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_DIR = os.path.join(SCRIPT_DIR, global_constants.JSONDATA)

async def process_file(filename, pool):
    filepath = os.path.join(JSON_DIR, filename)
    logger.info(f"Processing {filename}...")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            products = json.load(f)
        
        inserted = await insert_products(pool, "products", products)
        logger.info(f"Inserted {inserted}/{len(products)} products from {filename}")
        return len(products), inserted
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in {filename}", exc_info=True)
        return 0, 0
    except Exception as e:
        logger.error(f"Error processing {filename}: {e}", exc_info=True)
        return 0, 0

async def run_dump():
    pool = await create_pool()
    await setup_partitioned_table(pool, global_constants.PRODUCTS_TABLE)
    
    total_processed = 0
    total_inserted = 0
    start_time = datetime.now()
    
    if not os.path.exists(JSON_DIR):
        logger.error(f"JSON directory not found at: {JSON_DIR}")
        return
        
    files = [f for f in os.listdir(JSON_DIR) if f.endswith('.json')]
    if not files:
        logger.info("No JSON files found to process")
        return
    
    tasks = [process_file(f, pool) for f in files]
    results = await asyncio.gather(*tasks)
    
    for processed, inserted in results:
        total_processed += processed
        total_inserted += inserted
    
    logger.info(f"Processing completed in {datetime.now() - start_time}")
    logger.info(f"Total products processed: {total_processed}")
    logger.info(f"Total products inserted: {total_inserted}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(run_dump())