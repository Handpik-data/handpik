from abc import ABC, abstractmethod
import logging
import random
import logging
import shutil
import datetime
from datetime import datetime
import os
import json
import threading
import asyncio
import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from urllib.parse import urlparse


class BaseScraper(ABC):
    def __init__(self, base_url, logger_name, proxies=None, request_delay=1, max_retries=5):
        self.base_url = base_url
        self.logger = logging.getLogger(logger_name)
        self.request_delay = request_delay
        self.max_retries = max_retries
        self.proxies = proxies or []
        self._initialize_user_agents()
        self.timeout = ClientTimeout(total=30)
        self.session = None
        self.loop = None
        self.thread = None
        self.store_name = None
        self.module_dir = None
        self.domain = urlparse(base_url).netloc
        
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "Referer": self.base_url
        }

    def _initialize_user_agents(self):
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 13.5; rv:109.0) Gecko/20100101 Firefox/117.0",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Mobile/15E148 Safari/604.1"
        ]

    def start(self):
        self.thread = threading.Thread(target=self._run_in_thread)
        self.thread.daemon = True
        self.thread.start()
        return self

    def _run_in_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_start())
        except Exception as e:
            self.log_error(f"Scraper crashed: {str(e)}")
        finally:
            if self.session:
                self.loop.run_until_complete(self.session.close())

    async def _async_start(self):
        connector = TCPConnector(limit_per_host=2)
        self.session = ClientSession(
            headers={'User-Agent': random.choice(self.user_agents)},
            timeout=self.timeout,
            connector=connector,
            trust_env=True
        )
        try:
            await self.scrape_data()
        except Exception as e:
            self.log_error(f"Error in scrape_data: {str(e)}")
        finally:
            if not self.session.closed:
                await self.session.close()

    async def make_request(self, url, method='GET', **kwargs):
        
        delay = self.request_delay * (0.5 + random.random())
        await asyncio.sleep(delay)
        
        headers = kwargs.pop('headers', {})
        headers['User-Agent'] = random.choice(self.user_agents)
        
        proxy = random.choice(self.proxies) if self.proxies else None
        proxy_url = f"http://{proxy}" if proxy else None
        
        for attempt in range(self.max_retries):
            try:
                async with self.session.request(
                    method,
                    url,
                    headers=headers,
                    proxy=proxy_url,
                    ssl=False,
                    **kwargs
                ) as response:
                    if response.status == 429:
                        retry_after = response.headers.get('Retry-After', 10)
                        try:
                            wait_time = int(retry_after)
                        except ValueError:
                            wait_time = min(30, 5 * (attempt + 1))  # Max 30s wait
                        
                        self.log_info(f"429 Too Many Requests. Retrying after {wait_time}s")
                        await asyncio.sleep(wait_time)
                        continue  
                    
                    response.raise_for_status()
                    return await response.text()
                    
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if hasattr(e, 'status') and e.status == 429:
                    wait_time = min(30, 5 * (attempt + 1))
                    self.log_info(f"429 Detected. Waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    continue
                    
                if attempt < self.max_retries - 1:
                    delay = 1.5 * (2 ** attempt) 
                    self.log_debug(f"Retry {attempt+1}/{self.max_retries} for {url} after {delay}s")
                    await asyncio.sleep(delay)
                else:
                    self.log_error(f"Request failed: {method} {url} | Error: {str(e)}")
                    return None

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
    
    def save_data(self, data):
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
