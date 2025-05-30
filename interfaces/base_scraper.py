from abc import ABC, abstractmethod
import logging

class BaseScraper(ABC):
    def __init__(self, base_url, logger_name):
        self.base_url = base_url
        self.logger = logging.getLogger(logger_name)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

    @abstractmethod
    def scrape_pdp(self, product_link):
        pass

    @abstractmethod
    def scrape_products_links(self, url):
        pass

    @abstractmethod
    def scrape_category(self, url):
        pass

    def log_error(self, message):
        self.logger.error(message, exc_info=True)

    def log_info(self, message):
        self.logger.info(message)

    def log_debug(self, message):
        self.logger.debug(message)