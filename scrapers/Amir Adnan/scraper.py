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
from utils.LoggerConstants import AMIR_ADNAN
from urllib.parse import urljoin
from urllib.parse import urlsplit, urlunsplit, urljoin

import time


class AmirAdnan_Scrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=3):
        super().__init__(
            base_url="https://amiradnan.com/",
            logger_name=AMIR_ADNAN,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "saeedghani"
        self.all_product_links_ = []


    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        filepath = os.path.join(self.module_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filepath, 'r') as file:
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
            'brand':None,
            'category':None,
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
            response = await self.async_make_request(product_link)
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
                    sku_div = product_info_main.find('div', class_='sku-product')
                    if sku_div:
                        sku_span = sku_div.find('span')
                        if sku_span:
                            product_data["sku"] = sku_span.get_text(strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's sku: {e}")

                try:
                    # Description
                    description_div = soup.select_one('div.short-description')
                    if description_div:
                        for br in description_div.find_all('br'):
                            br.replace_with('\n')
                        paragraphs = [
                            tag.get_text(separator='\n', strip=True).replace('\xa0', ' ')
                            for tag in description_div.find_all(['p', 'span'])
                        ]
                        product_data['description'] = '\n'.join(paragraphs)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's description: {e}")

                try:
                    # Sizes
                    swatch_container = soup.select_one('div.swatch[data-option-index="0"]')
                    if swatch_container:
                        size_divs = swatch_container.select('div.swatch-element')

                        sizes_with_status = []

                        for size_div in size_divs:
                            size = size_div.get('data-value')
                            class_list = size_div.get('class', [])

                            # Check if 'soldout' is in the class list
                            is_available = 'soldout' not in class_list

                            sizes_with_status.append({
                                'size': size,
                                'available': is_available
                            })

                        product_data['variants'] = sizes_with_status if sizes_with_status else None
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product sizes: {e}")

                try:
                    prices_div = soup.find('div', class_='prices')
                    if prices_div:
                        sale_price_text = ''
                        original_price_text = ''

                        # Extract sale price
                        sale_price_tag = prices_div.select_one('span.price.on-sale span.money')
                        if sale_price_tag:
                            sale_price_text = sale_price_tag.get_text(strip=True)
                            cleaned_sale = re.sub(r'[^\d.,]', '', sale_price_text).lstrip('.')
                            product_data['sale_price'] = cleaned_sale

                        # Extract original (compare-at) price
                        original_price_tag = prices_div.select_one('span.compare-price span.money')
                        if original_price_tag:
                            original_price_text = original_price_tag.get_text(strip=True)
                            cleaned_original = re.sub(r'[^\d.,]', '', original_price_text).lstrip('.')
                            product_data['original_price'] = cleaned_original

                        # Extract currency from either price
                        currency_source = sale_price_text or original_price_text or ''
                        currency_match = re.search(r'(PKR|Rs|₹|\$|€|£)', currency_source)
                        if currency_match:
                            product_data['currency'] = currency_match.group(1)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's prices: {e}")


                try:
                    breadcrumb_div = soup.find("div", class_="breadcrumb layout-breadcrumb--skin1")
                    if breadcrumb_div:
                        breadcrumb_elements = breadcrumb_div.find_all(['a', 'span'])
                        product_data['attributes']["breadcrumb"] = [
                            elem.get_text(strip=True) for elem in breadcrumb_elements if elem.get_text(strip=True)
                        ]
                except Exception as e:
                    self.log_debug(f"Exception occurred while parsing breadcrumb: {e}")

                try:
                    # Images extraction
                    image_links = []
                    media_divs = soup.select('div.product-single__media a[data-image]')
                    for a_tag in media_divs:
                        img_url = a_tag.get('data-zoom-image') or a_tag.get('data-image')
                        if img_url:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            image_links.append(img_url)
                    product_data['images'] = image_links
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product images: {e}")

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}
    
    async def scrape_products_links(self, url):
                all_product_links = []
                page_number = 1

                # Strip URL fragment (like #Pret)
                split_url = urlsplit(url)
                url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, split_url.query, ''))
                current_url = url

                while True:
                    try:
                        self.log_info(f"Scraping page {page_number}: {current_url}")
                        response = requests.get(current_url, headers=self.headers, timeout=10)
                        response.raise_for_status()

                        soup = BeautifulSoup(response.text, 'html.parser')

                        product_anchors = soup.select('a[href^="/collections/"][href*="/products/"]')

                        if not product_anchors:
                            self.log_info(f"No product links found on page {page_number}. Stopping.")
                            break

                        for anchor in product_anchors:
                            product_url = urljoin(self.base_url, anchor['href'])
                            if product_url not in all_product_links:
                                all_product_links.append(product_url)

                        page_number += 1
                        current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

                    except Exception as e:
                        self.log_error(f"Error scraping page {page_number}: {e}")
                        break

                self.log_info(f"Collected {len(all_product_links)} unique product links.")
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
                saved_path = self.save_data(final_data)
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")
