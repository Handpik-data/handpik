import json
import logging.config
import asyncio
from scrapers.Amir_Adnan.scraper import AmirAdnan_Scrapper
from scrapers.EgoScraper.scraper import EgoScrapper
from scrapers.ImageScraper.scraper import ImageScraper
from scrapers.alkaram.scraper import AlkaramScraper
from scrapers.beechtree.scraper import Beechtree_Scrapper
from scrapers.diners.scraper import DinnerScraper
from scrapers.ethinic.scraper import EthinicScraper
from scrapers.generations.scraper import GenerationScraper
from scrapers.hushpuppies.scraper import HushpuppiesScraper
from scrapers.insigma.scraper import insigma_scraper
from scrapers.khaddi_scrapper.scraper import KhaddiScrapper
from scrapers.nakoosh.scraper import nakoosh_Scrapper



def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

async def main():
    setup_logging()
    scrapers = [
        AmirAdnan_Scrapper(),
        EgoScrapper(),
        ImageScraper(),
        AlkaramScraper(),
        Beechtree_Scrapper(),
        DinnerScraper(),
        EthinicScraper(),
        GenerationScraper(),
        HushpuppiesScraper(),
        insigma_scraper(),
        KhaddiScrapper(),
        nakoosh_Scrapper()
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