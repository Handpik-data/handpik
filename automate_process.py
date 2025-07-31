import asyncio
import os
import shutil
import datetime
import logging
from run_scrapers import run_scraping
from dump_products import run_dump
from dump_enhanced_description import run_enhancement
import global_constants

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper_scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def move_old_data():
    json_dir = global_constants.JSONDATA
    oldjsondata_dir = global_constants.OLDJSONDATA
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(oldjsondata_dir, timestamp)
    
    os.makedirs(target_dir, exist_ok=True)
    
    if not os.path.exists(json_dir):
        os.makedirs(json_dir, exist_ok=True)
        logger.info("Created jsondata directory as it didn't exist")
        return

    moved_count = 0
    for filename in os.listdir(json_dir):
        if filename.endswith('.json'):
            src = os.path.join(json_dir, filename)
            dst = os.path.join(target_dir, filename)
            try:
                shutil.move(src, dst)
                moved_count += 1
            except Exception as e:
                logger.error(f"Error moving {filename}: {str(e)}")
    
    logger.info(f"Moved {moved_count} files to {target_dir}")


    json_dir = global_constants.ENHANCEDDATA
    oldjsondata_dir = global_constants.OLDENHANCEDDATA
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = os.path.join(oldjsondata_dir, timestamp)
    
    os.makedirs(target_dir, exist_ok=True)
    
    if not os.path.exists(json_dir):
        os.makedirs(json_dir, exist_ok=True)
        logger.info("Created enhanced jsondata directory as it didn't exist")
        return

    moved_count = 0
    for filename in os.listdir(json_dir):
        if filename.endswith('.json'):
            src = os.path.join(json_dir, filename)
            dst = os.path.join(target_dir, filename)
            try:
                shutil.move(src, dst)
                moved_count += 1
            except Exception as e:
                logger.error(f"Error moving {filename}: {str(e)}")
    
    logger.info(f"Moved {moved_count} files to {target_dir}")

async def run_scraping_flow():
    logger.info("Starting scraping workflow")
    
    logger.info("Archiving previous data")
    move_old_data()
    
    logger.info("Running scrapers")
    await run_scraping()
   
    logger.info("Loading data to database")
    await run_dump()

    logger.info("Enhancing descriptions")
    await run_enhancement()
    
    logger.info("Scraping workflow completed successfully")

if __name__ == "__main__":
    asyncio.run(run_scraping_flow())