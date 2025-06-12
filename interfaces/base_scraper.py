from abc import ABC, abstractmethod
import logging
import random
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class BaseScraper(ABC):
    def __init__(self, base_url, logger_name, proxies=None, request_delay=3.5, max_retries=5):
        self.base_url = base_url
        self.logger = logging.getLogger(logger_name)
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.proxies = proxies or []
        self.session = self._create_session()
        self._initialize_user_agents()
        
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive"
        }

    def _create_session(self):
        session = requests.Session()
        
        retry_kwargs = Retry(
            total=self.max_retries,
            backoff_factor=0.8,
            status_forcelist=[
                429,500,502,503,504,509,510,511,512 
            ],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )

        try:
            from urllib3.util import Retry
            if hasattr(Retry, 'DEFAULT_RETRY_AFTER_STATUS_CODES'):
                retry_kwargs['retry_on_timeout'] = True
        except ImportError:
            pass

        retry_strategy = Retry(**retry_kwargs)
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=100,
            pool_maxsize=100
        )
        
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        return session

    def _initialize_user_agents(self):
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.5; rv:109.0) Gecko/20100101 Firefox/117.0",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
        ]

    def _get_random_user_agent(self):
        return random.choice(self.user_agents)

    def _get_random_proxy(self):
        return random.choice(self.proxies) if self.proxies else None

    def _throttle_request(self):
        time.sleep(self.request_delay * (0.8 + 0.4 * random.random()))

    def make_request(self, url, method='GET', **kwargs):
        self._throttle_request()
        
        headers = kwargs.pop('headers', {})
        headers['User-Agent'] = self._get_random_user_agent()
        proxies = {'https': self._get_random_proxy(), 'http': self._get_random_proxy()} if self.proxies else None
        
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                proxies=proxies,
                timeout=(20, 40),  
                **kwargs
            )
            response.raise_for_status()
            return response
            
        except requests.exceptions.RequestException as e:
            status_code = e.response.status_code if hasattr(e, 'response') else 'N/A'
            self.log_error(f"Request failed: {method} {url} | Status: {status_code} | Error: {str(e)}")
            raise

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