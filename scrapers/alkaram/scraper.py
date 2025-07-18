import os
import re
import json
import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import ALKARAM_LOGGER
from urllib.parse import urljoin, urlparse
import time


class AlkaramScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.alkaramstudio.com/",
            logger_name=ALKARAM_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "alkaramstudio"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        filepath = os.path.join(self.module_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filepath, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))

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
            "attributes": {},
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                title_tag = soup.select_one('h1.t4s-product__title')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting title: {str(e)}', 'product_link': product_link}

            try:
                sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting SKU: {str(e)}', 'product_link': product_link}

            try:
                price_div = soup.find('div', class_='t4s-product-price')
                original_price = sale_price = currency = None

                if price_div:
                    price_text = price_div.get_text(strip=True)

                    currency_match = re.match(r'^([^\d\s]+)', price_text)
                    if currency_match:
                        currency = currency_match.group(1)

                    price_numbers = re.findall(r'\d[\d,]*', price_text)
                    price_numbers = [p.replace(',', '') for p in price_numbers]

                    if len(price_numbers) >= 1:
                        original_price = price_numbers[0]
                    if len(price_numbers) >= 2:
                        sale_price = price_numbers[1]

                    data_price = price_div.get('data-price')
                    if data_price and not original_price:
                        original_price = str(int(data_price) // 100)

                product_data['original_price'] = original_price
                product_data['sale_price'] = sale_price
                product_data['currency'] = currency  
            except Exception as e:
                return {'error': f'Exception occurred while extracting pricing: {str(e)}', 'product_link': product_link}

            try:
                image_elements = soup.select('img[data-master]')
                for img in image_elements:
                    src = img.get('data-master')
                    if src and src not in product_data['images']:
                        full_url = urljoin(self.base_url, src)
                        product_data['images'].append(full_url)
            except Exception as e:
                return {'error': f'Exception occurred while extracting images: {str(e)}', 'product_link': product_link}

            
  
            try:
                size_container = soup.find('div', {'class': 't4s-swatch__list'})
                if size_container:
                    size_elements = size_container.find_all('div', {'data-swatch-item': ''})
                    for size_element in size_elements:
                        size_value = size_element.get_text(strip=True)

                        is_available = 'is--soldout' not in size_element.get('class', [])

                        variant_data = {
                            'size': size_value,
                            'availability': is_available  
                        }

                        product_data['variants'].append(variant_data)
            except Exception as e:
                return {'error': f'Exception occurred while extracting variants/sizes: {str(e)}', 'product_link': product_link}
            
                 
            try:
                breadcrumb = soup.find('nav', class_='t4s-pr-breadcrumb')
                breadcrumb_path = []

                if breadcrumb:
                    items = breadcrumb.find_all(['a', 'span'])
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and text != 'Home': 
                            breadcrumb_path.append(text)

                product_data['category'] = breadcrumb_path

            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}


            try:

                description_container = soup.find('div', id='t4s-tab-destemplate--16602647167156__main')
               
                if description_container:

                    product_data['description'] = description_container.get_text(separator="\n", strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's description: {e}")

            try:
                breadcrumb_nav = soup.select_one('nav.t4s-pr-breadcrumb')
                if breadcrumb_nav:
                    breadcrumb_items = []

                    breadcrumb_links = breadcrumb_nav.find_all('a')
                    for link in breadcrumb_links:
                        breadcrumb_items.append(link.get_text(strip=True))

                    breadcrumb_span = breadcrumb_nav.find('span')
                    if breadcrumb_span:
                        breadcrumb_items.append(breadcrumb_span.get_text(strip=True))

                    product_data['attributes']['breadcrumbs'] = breadcrumb_items

            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}


            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}

            try:
                shipping_div = soup.find('div', id='t4s_tab_c1f78054-ee99-4f40-89e2-f342a6fcebc3')
                if shipping_div:
                    shipping_text = shipping_div.get_text(separator="\n", strip=True)
                    product_data['raw_data']['shipping_and_handling'] = shipping_text

                disclaimer_div = soup.find('div', class_='tab--disclaimer')
                if disclaimer_div:
                    disclaimer_text = disclaimer_div.get_text(separator=' ', strip=True)
                    product_data['raw_data']['disclaimer'] = disclaimer_text

            except Exception as e:
                return {'error': f'Exception occurred while extracting shipping/handling or disclaimer: {str(e)}', 'product_link': product_link}


        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data


    
    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')
                product_links = soup.select('a.t4s-full-width-link')

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = f"{self.base_url}{href}"
                        all_product_links.append(product_url)

                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        # Debug: Print the collected links
        self.log_info(f"Collected {len(all_product_links)} product links.")
        return all_product_links
            
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
                saved_path = await self.save_data(final_data)  # ✅ FIXED
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")