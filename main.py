import json
import logging.config
import asyncio
from scrapers.bonanza.scraper import BonanzaScraper




def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

async def main():
    setup_logging()
    scrapers = [
        BonanzaScraper()
    ]
    tasks = [scraper.scrape_data() for scraper in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            print("A scraper task failed:", result)
        else:
            print("A scraper completed:", result)

if __name__ == "__main__":
    asyncio.run(main())