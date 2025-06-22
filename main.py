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
from scrapers.EgoScraper.scraper import EgoScrapper  
from scrapers.almirah.scraper import almirahscraper 
from scrapers.ImageScraper.scraper import ImageScraper  
from scrapers.ethinic.scraper import EthinicScraper  
from scrapers.generations.scraper import GenerationScraper  
from scrapers.hushpuppies.scraper import HushpuppiesScraper  
from scrapers.Ismailfareed.scraper import ismailfareedscaper 
from scrapers.chinyere.scraper import chinyerescraper  
from scrapers.alkaram.scraper import AlkaramScraper  
from scrapers.khaddi_scrapper.scraper import KhaddiScrapper  
from scrapers.diners.scraper import DinnerScraper  
from scrapers.nakoosh.scraper import nakoosh_Scrapper  
from scrapers.insigma.scraper import insigma_scraper  
from scrapers.Amir_Adnan.scraper import AmirAdnan_Scrapper  
from scrapers.beechtree.scraper import Beechtree_Scrapper  

















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
        SulafahScraper(),
        EgoScrapper(),
        almirahscraper(),
        ImageScraper(),
        EthinicScraper(),
        GenerationScraper(),
        HushpuppiesScraper(),
        ismailfareedscaper(),
        chinyerescraper(),
        AlkaramScraper(),
        KhaddiScrapper(),
        DinnerScraper(),
        nakoosh_Scrapper(),
        insigma_scraper(),
        AmirAdnan_Scrapper(),
        Beechtree_Scrapper()



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