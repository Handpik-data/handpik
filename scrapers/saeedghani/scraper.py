import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SAEEDGHANI_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4.element import NavigableString

class SaeedGhaniScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=3):
        super().__init__(
            base_url="https://saeedghani.pk",
            logger_name=SAEEDGHANI_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "saeedghani"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        if not os.path.exists(filename):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filename, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))
        
    async def clean_price_string(self, price_str):
        if not price_str:
            return None
        cleaned = re.sub(r'(Rs\.?|,|\s)', '', price_str)
        return cleaned
        
    async def scrape_pdp(self, product_link):        
                
        if product_link in self.all_product_links_:
            return None
        
        self.all_product_links_.append(product_link)
        product_data = {
            'store_name': self.store_name,
            'title': None,
            'sku': None,
            'description': None,
            'currency': None,
            'original_price': None,
            'sale_price': None,
            'images': [],
            'brand': None,
            'availability': None,
            'category': None,
            'product_url': product_link,
            'variants': [],
            'attributes': {},
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(
                product_link
            )
            soup = BeautifulSoup(response.text, "html.parser")

            product_info_main = soup.find('div', class_="product-default")
            if product_info_main:
                try:
                    page_title_wrapper = product_info_main.find_all('h1', class_="product-title")
                    if page_title_wrapper:
                        page_title_span = page_title_wrapper[0].find('span')
                        product_data["title"] = page_title_span.get_text(strip=True)
                    
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's title : {e}")
                
                try:
                    prices_div = product_info_main.find('div', class_='prices')
                    compare_price = prices_div.find('span', class_='compare-price')
                    if compare_price:
                        compare_price = await self.clean_price_string(compare_price.find('span', class_='money').get_text(strip=True))
                        on_sale = await self.clean_price_string(prices_div.find('span', class_='on-sale').find('span', class_='money').get_text(strip=True))

                        product_data['original_price'] = compare_price
                        product_data['sale_price'] = on_sale
                    else:
                        product_data['original_price'] = await self.clean_price_string(prices_div.find('span', class_='money').get_text(strip=True))

                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's prices : {e}")
                
                try:
                    collapse_links = product_info_main.find_all('a', attrs={'data-toggle': 'collapse'})

                    for link in collapse_links:
                        main_text = ''.join(link.find_all(text=True, recursive=False)).strip()
                        target_div = product_info_main.find('div', class_='panel-collapse', id=link['href'][1:])
                        text = target_div.get_text(separator='\n', strip=True)
                        if main_text == 'What It Is':
                            product_data['description'] = text
                        else:
                            product_data['attributes'][main_text] = text

                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's collapse : {e}")

                try:
                    image_links = []
                    product_photos = soup.find('div', class_="product-photos")

                    for img in product_photos.find_all('img'):
                        src = img.get('src')
                        if src:
                            image_links.append(src.strip())

                    for a in product_photos.find_all('a'):
                        href = a.get('href')
                        if href and any(href.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                            image_links.append(href.strip())

                    image_links = list(set(image_links))

                    product_data['images'] = ['https:' + link if link.startswith('//') else link for link in image_links]
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's images : {e}")
        
            
        except Exception as e:
            self.log_error(f"An error occurred while scraping PDP: {e}")
        
        return product_data
    
    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1
        current_url = url
        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(
                    current_url
                )
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                main_div = soup.find('div', class_='product-collection')

                if main_div:

                    product_links = main_div.find_all(
                        lambda tag: tag.name == 'a' and
                        tag.has_attr('class') and
                        'product-grid-image' in tag['class'] and
                        'cstm-url' in tag['class']
                    )
                    self.log_info(f"{len(product_links)} products on page {page_number}") 
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    for link in product_links:
                        href = self.base_url + link['href']
                        all_product_links.add(href)
                else:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
       
                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"
                
            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break
        
        return list(all_product_links)

    async def scrape_category(self, url):
        all_products = []
        all_products_links = await self.scrape_products_links(url)
        for product_link in all_products_links:
            pdp_data = await self.scrape_pdp(product_link)
            if pdp_data is not None:
                all_products.append(pdp_data)
        
        return all_products
    
    async def scrape_data(self):
        final_data = []
        try:
            category_urls = await self.get_unique_urls_from_file(
                os.path.join(self.module_dir, "categories.txt")
            )
            for url in category_urls:
                products = await self.scrape_category(url)
                final_data.extend(products)
            if final_data:
                saved_path = self.save_data(final_data)
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")