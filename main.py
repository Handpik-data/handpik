import json
import logging.config
import asyncio
from scrapers.zeenwoman.scraper import ZeeWomanScraper
from scrapers.wovworld.scraper import WovWorldScraper
from scrapers.sulafah.scraper import SulafahScraper

def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

async def main():
    setup_logging()
    scraper = SulafahScraper()
    await scraper.scrape_data()

if __name__ == "__main__":
    asyncio.run(main())