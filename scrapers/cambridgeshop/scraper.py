import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import CAMBRIDGESHOP_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class CambridgeShopScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=3):
        super().__init__(
            base_url="https://thecambridgeshop.com",
            logger_name=CAMBRIDGESHOP_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "cambridgeshop"
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
            product_info_main = soup.find('div', class_="t4s-product__info-wrapper")
            if product_info_main:
                try:
                    page_title_wrapper = product_info_main.find('h1', class_="t4s-product__title")
                    if page_title_wrapper:
                        product_data["title"] = page_title_wrapper.get_text(strip=True)
                    
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's title : {e}")

                try:
                    page_price_wrapper = product_info_main.find('div', class_="t4s-product-price")
                    if page_price_wrapper:
                        page_price_span = page_price_wrapper.find('span')
                        product_data["original_price"] = await self.clean_price_string(page_price_span.get_text(strip=True))
                    
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's price : {e}")
                

                try:
                    variants_script = product_info_main.find('script', class_='pr_variants_json')
                    
                    if variants_script:
                    
                        variants_data = json.loads(variants_script.string)
                        
                        result = []
                        for variant in variants_data:
                            result.append({
                                "size": variant.get("option2", ""),
                                "color": variant.get("option1", ""),
                                "availability": variant.get("available", False)
                            })

                            product_data['variants'] = result

                        
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's variants availability : {e}")
            
            product_image_main = soup.find('div', class_="t4s-product__media-wrapper")
            
            try: 
                images = []
                if product_image_main:
                    image_container = product_image_main.find_all('div', class_='t4s-product__media')
                    for div in image_container:
                        img = div.find('img')
                        if img:
                            img_url = img.get('data-master') or img.get('data-srcset') or img.get('src')
                            if img_url:
                                if img_url.startswith("//"):
                                    images.append("https:" + img_url)
                product_data['images'] = images
            except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's images : {e}")

            try:
                desc_div = product_info_main.find('div', class_='full description')

                data = {}
                if desc_div:
                    for p in desc_div.find_all('p'):
                        strong_tag = p.find('strong')
                        if strong_tag:
                            key = strong_tag.get_text(strip=True).replace(':', '')
                            full_text = p.get_text(strip=True)
                            value = full_text.replace(strong_tag.get_text(strip=True), '').strip()
                            data[key] = value

                for key, value in data.items():
                    if key == 'Product Details':
                        product_data['description'] = value
                    else:
                        product_data['attributes'][key] = value
            
            except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's description : {e}")
            
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
                
                main_div = soup.find('div', class_='t4s-main-collection-page')

                if main_div:

                    product_links = main_div.find_all('a', class_='t4s-full-width-link')
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