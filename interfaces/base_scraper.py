from abc import ABC, abstractmethod
import logging
import random
import time
import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import asyncio
import os
import json
import shutil
from datetime import datetime

class BaseScraper(ABC):
    def __init__(self, base_url, logger_name, proxies=None, request_delay=0.1, max_retries=5):
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
        
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=0.8,
            status_forcelist=[
                429,500,502,503,504,509,510,511,512 
            ],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=5,
            pool_maxsize=5
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

    def _throttle_request(self, url, attempt):
        time_delay = self.request_delay * (0.8 + 0.4 * random.random())
        self.log_info(f"Attempt {attempt+1} for url {url} throttle request time {time_delay}")
        time.sleep(time_delay)

    def make_request(self, url, method='GET'):
        
        max_attempts = self.max_retries
        attempt = 0

        while attempt < max_attempts:
            self.log_info(f"Attempt {attempt+1} for url {url}")
            self._throttle_request(url,attempt)
            headers = self.headers
            headers['User-Agent'] = self._get_random_user_agent()
            self.log_info(f"Attempt {attempt + 1} of {max_attempts} - Requesting URL: {url}")

            try:
                response = self.session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=(20, 40), 
                    verify=False 
                )
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    wait_time = int(retry_after) if retry_after and retry_after.isdigit() else (2 ** attempt)
                    self.log_warning(f"Received 429 status. Waiting {wait_time} seconds before retrying.")
                    time.sleep(wait_time)
                    attempt += 1
                    continue
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                attempt += 1
                backoff = 2 ** attempt
                self.log_warning(f"Attempt {attempt} failed for {url}. Backing off for {backoff} seconds. Error: {str(e)}")
                time.sleep(backoff)
        raise requests.exceptions.HTTPError(f"All attempts failed for: {url}")
    
    async def async_make_request(self, url, method='GET'):
        return await asyncio.to_thread(self.make_request, url, method)

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
        self.logger.debug(message, exc_info=True)
    
    def log_warning(self, message):
        self.logger.warning(message)
    
    async def save_data(self, data):
        if not data:
            self.log_error("No data to save")
            return None
            
        try:
            project_root = os.path.abspath(os.path.join(
                os.path.dirname(__file__), '..'
            ))
            
            json_dir = os.path.join(project_root, "jsondata")
            old_dir = os.path.join(project_root, "oldjsondata")
            os.makedirs(json_dir, exist_ok=True)
            os.makedirs(old_dir, exist_ok=True)

            current_file = os.path.join(json_dir, f"{self.store_name}.json")
            old_file = None

            if os.path.exists(current_file):
                ctime = os.path.getctime(current_file)
                timestamp = datetime.fromtimestamp(ctime).strftime("%Y%m%d_%H%M%S")
                
                old_filename = f"{self.store_name}_{timestamp}.json"
                old_file = os.path.join(old_dir, old_filename)
                
                shutil.move(current_file, old_file)
                self.log_info(f"Moved old data to {old_file}")

            with open(current_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            
            self.log_info(f"Saved new data to {current_file}")
            return current_file
            
        except Exception as e:
            self.log_error(f"Error saving data: {str(e)}")
            return None