import json
import logging.config
from scrapers.zeenwoman.scraper import ZeeWomanScraper

def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

if __name__ == "__main__":
    setup_logging()
    
    zeeWomanScraper = ZeeWomanScraper()
    zeeWomanScraper.scrape_data()
    