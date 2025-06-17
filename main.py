import json
import logging.config
import threading
import time
from scrapers.zeenwoman.scraper import ZeeWomanScraper
from scrapers.wovworld.scraper import WovWorldScraper
from scrapers.sputnikfootwear.scraper import SputnikFootWearScraper
from scrapers.speedsports.scraper import SpeedSportsScraper
from scrapers.sheepofficial.scraper import SheepOfficialScraper
from scrapers.shaffer.scraper import ShafferScraper
from scrapers.sapphireonline.scraper import SapphireScraper
from scrapers.saya.scraper import SayaScraper
from scrapers.sanasafinaz.scraper import SanaSafinazScraper
from scrapers.saeedghani.scraper import SaeedGhaniScraper
from scrapers.cambridgeshop.scraper import CambridgeShopScraper
from scrapers.sulafah.scraper import SulafahScraper

def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

def run_scraper(scraper):
    try:
        scraper.start()
        return scraper
    except Exception as e:
        logging.getLogger(scraper.logger_name).error(
            f"Error starting {scraper.store_name} scraper: {str(e)}", exc_info=True
        )
        return None

def main():
    setup_logging()
    logger = logging.getLogger("main")
    
    scrapers = [
        ZeeWomanScraper(),
        WovWorldScraper(),
        SputnikFootWearScraper(),
        SpeedSportsScraper(),
        SheepOfficialScraper(),
        ShafferScraper(),
        SapphireScraper(),
        SayaScraper(),
        SanaSafinazScraper(),
        SaeedGhaniScraper(),
        CambridgeShopScraper(),
        SulafahScraper()
    ]
    
    logger.info(f"Starting {len(scrapers)} scrapers in parallel threads")
    
    threads = []
    for scraper in scrapers:
        thread = threading.Thread(target=run_scraper, args=(scraper,))
        thread.daemon = True
        thread.start()
        threads.append((scraper, thread))
    
    try:
        while any(thread.is_alive() for _, thread in threads):
            time.sleep(5)  
            
            status_report = []
            for scraper, thread in threads:
                status = "RUNNING" if thread.is_alive() else "COMPLETED"
                status_report.append(f"{scraper.store_name}: {status}")
            
            logger.info(" | ".join(status_report))
                
    except KeyboardInterrupt:
        logger.info("Shutting down scrapers due to keyboard interrupt...")
    finally:
        logger.info("All scrapers completed")

if __name__ == "__main__":
    main()