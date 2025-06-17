import json
import logging.config
import asyncio
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

async def main():
    setup_logging()
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
    tasks = [scraper.scrape_data() for scraper in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            print("A scraper task failed:", result)
        else:
            print("A scraper completed:", result)

if __name__ == "__main__":
    asyncio.run(main())