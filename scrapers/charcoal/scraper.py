import os
import re
import json
import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import Charcoal_LOGGER
from urllib.parse import urljoin, urlparse
import time


class CharCoalScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://charcoal.com.pk/",
            logger_name=Charcoal_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )   
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Charcoal"
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
            'attributes': {},
            'raw_data': {}  
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # 🔹 Scrape Title
            try:
                title_div = soup.find('div', class_='product-info__block-item', attrs={'data-block-type': 'title'})
                if title_div:
                    product_title_tag = title_div.find('h1', class_='product-info__title h3')
                    if product_title_tag:
                        product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception while scraping title: {e}")

            # 🔹 Scrape SKU
            try:
                sku_div = soup.find('div', class_='product-info__block-item', attrs={'data-block-type': 'sku'})
                if sku_div:
                    variant_sku_tag = sku_div.find('variant-sku')
                    if variant_sku_tag:
                        sku_text = variant_sku_tag.get_text(strip=True).replace('SKU:', '').strip()
                        product_data['sku'] = sku_text
            except Exception as e:
                self.log_debug(f"Exception while scraping SKU: {e}")

            # 🔹 Scrape Prices
            try:
                sale_price = None
                original_price = None
                currency = None

                sale_tag = soup.find('sale-price')
                if sale_tag:
                    sale_text = sale_tag.get_text(strip=True)
                    currency_match = re.search(r'(Rs\.)', sale_text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    sale_price_value = re.search(r'(\d[\d,\.]*)', sale_text)
                    sale_price = sale_price_value.group(1).replace(",", "") if sale_price_value else None

                original_tag = soup.find('compare-at-price')
                if original_tag:
                    original_text = original_tag.get_text(strip=True)
                    if not currency:
                        currency_match = re.search(r'(Rs\.)', original_text)
                        currency = currency_match.group(1).strip() if currency_match else None
                    original_price_value = re.search(r'(\d[\d,\.]*)', original_text)
                    original_price = original_price_value.group(1).replace(",", "") if original_price_value else None

                product_data['original_price'] = original_price
                product_data['sale_price'] = sale_price
                product_data['currency'] = currency
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")

            # 🔹 Scrape Images
            try:
                images_set = set()
                divs = soup.find_all('div', class_='product-gallery__media', attrs={'data-media-type': 'image'})
                for div in divs:
                    img_tag = div.find('img')
                    if img_tag:
                        img_url = None
                        srcset = img_tag.get('srcset')
                        if srcset:
                            srcset_items = [item.strip() for item in srcset.split(',')]
                            if srcset_items:
                                last_item = srcset_items[-1]
                                parts = last_item.split(' ')
                                if parts:
                                    img_url = parts[0]
                        if not img_url:
                            src = img_tag.get('src')
                            if src and not src.startswith('data:image'):
                                img_url = src
                        if img_url:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            elif img_url.startswith('/'):
                                img_url = 'https://charcoal.com.pk' + img_url
                            images_set.add(img_url)
                product_data['images'] = list(images_set)
            except Exception as e:
                self.log_debug(f"Exception while scraping images: {e}")

            # 🔹 Scrape Variants (Sizes, Availability)
            try:
                variants = []
                fieldset = soup.find('fieldset', class_='variant-picker__option')
                if fieldset:
                    inputs = fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in inputs:
                        size_value = None
                        availability = not input_tag.has_attr('disabled')
                        input_id = input_tag.get('id')
                        label = fieldset.find('label', {'for': input_id})
                        if label:
                            span = label.find('span')
                            if span:
                                size_value = span.get_text(strip=True)
                        if size_value:
                            variants.append({
                                "size": size_value,
                                "availability": availability
                            })
                product_data['variants'] = variants
            except Exception as e:
                self.log_debug(f"Exception while scraping variants: {e}")

            # 🔹 Scrape Description
            try:
                description_text = ""
                desc_div = soup.find('div', class_='product-info__block-item', attrs={'data-block-type': 'description'})
                if desc_div:
                    info_desc_div = desc_div.find('div', class_='product-info__description')
                    if info_desc_div:
                        prose_div = info_desc_div.find('div', class_='prose')
                        if prose_div:
                            li_items = prose_div.find_all('li')
                            desc_lines = [li.get_text(separator=" ", strip=True) for li in li_items if li.get_text(strip=True)]
                            description_text = ", ".join(desc_lines).strip()
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception while scraping description: {e}")

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data

 
    async def scrape_products_links(self, url):
        all_product_links = []

        try:
            # Ensure URL ends with '/'
            if not url.endswith('/'):
                url += '/'

            self.log_info(f"Scraping: {url}")

            # Make GET request to the page
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Find all <a> tags with href starting with '/products/'
            product_a_tags = soup.find_all('a', href=True)
            for a_tag in product_a_tags:
                href = a_tag['href']
                if href.startswith('/products/'):
                    product_url = urljoin(self.base_url, href)
                    if product_url not in all_product_links:
                        all_product_links.append(product_url)

            self.log_info(f"Collected {len(all_product_links)} product links from HTML page.")

        except Exception as e:
            self.log_error(f"Error scraping {url}: {e}")

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
