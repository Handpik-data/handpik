import json
import logging.config
import asyncio
from scrapers.Amir_Adnan.scraper import AmirAdnan_Scrapper
from scrapers.EgoScraper.scraper import EgoScrapper
from scrapers.ImageScraper.scraper import ImageScraper
from scrapers.Ismailfareed.scraper import ismailfareedscaper
from scrapers.JunaidJamshed.scraper import juniadjamshed
from scrapers.alkaram.scraper import AlkaramScraper
from scrapers.almirah.scraper import almirahscraper
from scrapers.beechtree.scraper import Beechtree_Scrapper
from scrapers.bonanza.scraper import BonanzaScraper
from scrapers.cambridgeshop.scraper import CambridgeShopScraper
from scrapers.chinyere.scraper import chinyerescraper
from scrapers.diners.scraper import DinnerScraper
from scrapers.ethinic.scraper import EthinicScraper
from scrapers.generations.scraper import GenerationScraper
from scrapers.hushpuppies.scraper import HushpuppiesScraper
from scrapers.insigma.scraper import insigma_scraper
from scrapers.khaddi_scrapper.scraper import KhaddiScrapper
from scrapers.nakoosh.scraper import nakoosh_Scrapper
from scrapers.saeedghani.scraper import SaeedGhaniScraper
from scrapers.sanasafinaz.scraper import SanaSafinazScraper
from scrapers.sapphireonline.scraper import SapphireScraper
from scrapers.saya.scraper import SayaScraper
from scrapers.shaffer.scraper import ShafferScraper
from scrapers.sheepofficial.scraper import SheepOfficialScraper
from scrapers.speedsports.scraper import SpeedSportsScraper
from scrapers.sputnikfootwear.scraper import SputnikFootWearScraper
from scrapers.sulafah.scraper import SulafahScraper
from scrapers.wovworld.scraper import WovWorldScraper
from scrapers.zeenwoman.scraper import ZeeWomanScraper


def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

async def run_scraping():
    setup_logging()
    scrapers = [
        AmirAdnan_Scrapper(),
        EgoScrapper(),
        ImageScraper(),
        ismailfareedscaper(),
        juniadjamshed(),
        AlkaramScraper(),
        almirahscraper(),
        Beechtree_Scrapper(),
        BonanzaScraper(),
        CambridgeShopScraper(),
        chinyerescraper(),
        DinnerScraper(),
        EthinicScraper(),
        GenerationScraper(),
        HushpuppiesScraper(),
        insigma_scraper(),
        KhaddiScrapper(),
        nakoosh_Scrapper(),
        SaeedGhaniScraper(),
        SanaSafinazScraper(),
        SapphireScraper(),
        SayaScraper(),
        ShafferScraper(),
        SheepOfficialScraper(),
        SpeedSportsScraper(),
        SputnikFootWearScraper(),
        SulafahScraper(),
        WovWorldScraper(),
        ZeeWomanScraper()
    ]
    tasks = [scraper.scrape_data() for scraper in scrapers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            print("A scraper task failed:", result)
        else:
            print("A scraper completed:", result)

if __name__ == "__main__":
    asyncio.run(run_scraping())