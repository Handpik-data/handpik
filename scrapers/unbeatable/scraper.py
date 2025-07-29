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
from utils.LoggerConstants import UNBEATABLE_LOGGER
from urllib.parse import urljoin, urlparse
import time


class UnbeatableScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.unbeatable.com.pk/pk/",
            logger_name=UNBEATABLE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "unbeatable"
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
            'raw_data': {
            }
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                product_name_div = soup.find('div', class_='product-name')
                if product_name_div:
                    product_title_tag = product_name_div.find('h1')
                    if product_title_tag:
                        product_data["title"] = product_title_tag.get_text(strip=True)
                    else:
                        product_data["title"] = None
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None


            try:
                    breadcrumbs = []
                    
                    # Find the main breadcrumbs container
                    breadcrumb_wrapper = soup.find('div', class_='breadcrumbs')
                    if breadcrumb_wrapper:
                        # Inside the breadcrumbs, find the correct 'container' that has <ul>
                        containers = breadcrumb_wrapper.find_all('div', class_='container')
                        for container in containers:
                            ul_tag = container.find('ul')
                            if ul_tag:
                                li_tags = ul_tag.find_all('li')
                                for li in li_tags:
                                    # Look for anchor tag first
                                    a_tag = li.find('a')
                                    if a_tag:
                                        crumb = a_tag.get_text(strip=True)
                                        breadcrumbs.append(crumb)
                                    else:
                                        # If no anchor, check for strong tag
                                        strong_tag = li.find('strong')
                                        if strong_tag:
                                            crumb = strong_tag.get_text(strip=True)
                                            breadcrumbs.append(crumb)
                                break  # Stop after first matching container with <ul>

                    # Save breadcrumbs in product_data
                    product_data['attributes']['breadcrumbs'] = breadcrumbs

            except Exception as e:
                    self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                    product_data['attributes']['breadcrumbs'] = []


            try:
                sku_div = soup.find('div', class_='attribute sku')
                if sku_div:
                    span_tag = sku_div.find('span')
                    if span_tag:
                        product_data['sku'] = span_tag.get_text(strip=True)
                    else:
                        product_data['sku'] = None
                else:
                    product_data['sku'] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product SKU: {e}")
                product_data['sku'] = None

            try:
                price_wrapper = soup.find('div', class_='price-box')
                if price_wrapper:
                    # Initialize
                    original_price = None
                    sale_price = None
                    currency = None

                    # Helper function to extract numeric price and currency
                    def extract_price_currency(price_str):
                        price_numeric = re.sub(r'[^\d.]', '', price_str)
                        currency_match = re.match(r'^(\D+)', price_str)
                        currency_value = currency_match.group(1).strip() if currency_match else None
                        return price_numeric, currency_value

                    # Extract old (original) price
                    old_price_p = price_wrapper.find('p', class_='old-price')
                    if old_price_p:
                        old_price_span = old_price_p.find('span', class_='price')
                        if old_price_span:
                            old_price_str = old_price_span.get_text(strip=True)
                            original_price, currency = extract_price_currency(old_price_str)

                    # Extract special (sale) price
                    special_price_p = price_wrapper.find('p', class_='special-price')
                    if special_price_p:
                        special_price_span = special_price_p.find('span', class_='price')
                        if special_price_span:
                            special_price_str = special_price_span.get_text(strip=True)
                            sale_price, currency_special = extract_price_currency(special_price_str)
                            # If currency not found from old price, use special price currency
                            if not currency:
                                currency = currency_special

                    # If no old/special price found, check for regular price as fallback
                    if not original_price and not sale_price:
                        regular_price_span = price_wrapper.find('span', class_='price')
                        if regular_price_span:
                            regular_price_str = regular_price_span.get_text(strip=True)
                            price_value, currency_value = extract_price_currency(regular_price_str)
                            original_price = price_value
                            currency = currency_value

                    # Set product data dictionary values
                    product_data['original_price'] = original_price
                    product_data['sale_price'] = sale_price
                    product_data['currency'] = currency

                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None


 


            try:
                breadcrumbs_div = soup.find('div', class_='breadcrumbs')
                categories = []

                if breadcrumbs_div:
                    ul = breadcrumbs_div.find('ul')
                    if ul:
                        li_tags = ul.find_all('li')
                        for li in li_tags:
                            if 'home' in li.get('class', []):
                                continue
                            a_tag = li.find('a')
                            if a_tag:
                                categories.append(a_tag.get_text(strip=True))
                            else:
                                strong_tag = li.find('strong')
                                if strong_tag:
                                    categories.append(strong_tag.get_text(strip=True))

                product_data["category"] = categories

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping categories from breadcrumbs: {e}")
                product_data["category"] = []

            variants = []

            try:
                sizes = []
                size_ul = soup.find('ul', id='configurable_swatch_size')
                if size_ul:
                    li_tags = size_ul.find_all('li')
                    for li in li_tags:
                        a_tag = li.find('a')
                        if a_tag:
                            span_label = a_tag.find('span', class_='swatch-label')
                            if span_label:
                                size_value = span_label.get_text(strip=True)
                                if size_value:
                                    # Check if 'disable-li' class is present in <li> tag
                                    li_classes = li.get('class', [])
                                    is_disabled_class = 'disable-li' in li_classes

                                    # Check if there is a <span class="disable"> overlay
                                    disable_span = li.find('span', class_='disable')
                                    is_disabled_span = disable_span is not None

                                    # For your provided tag, neither exists, so all are available
                                    availability = 'unavailable' if (is_disabled_class or is_disabled_span) else 'available'

                                    sizes.append({'size': size_value, 'availability': availability})

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes: {e}")

            colors = [{'availability': 'available'}]

            for size in sizes:
                combined_availability = (
                    'false'
                    if size['availability'] == 'unavailable'
                    else 'true'
                )
                variants.append({
                    'size': size['size'],
                    'availability': combined_availability
                })

            product_data['variants'] = variants



            try:
                product_images = []

                # Find all img tags with class 'owl-item'
                img_tags = soup.find_all('img', class_='owl-item')
                for img_tag in img_tags:
                    src_img_url = img_tag.get('src')
                    if src_img_url:
                        # Replace 'thumbnail/369x532' with 'image' or remove it for original quality
                        high_quality_url = re.sub(r'/thumbnail/\d+x\d+', '/image', src_img_url)
                        product_images.append(high_quality_url)

                # Remove duplicates if any
                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []



            try:
                description_section = soup.find('div', class_='std')
                if description_section:
                    # Extract and clean text
                    description_text = description_section.get_text(separator="\n", strip=True)
                    product_data['description'] = description_text
                else:
                    product_data['description'] = ""
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""


        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data



    async def scrape_products_links(self, start_url):
        from urllib.parse import urljoin

        all_product_links = set()  # Using set to avoid duplicates
        current_url = start_url

        while current_url:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Get all <a> tags with class 'product-image'
                product_links = soup.select('a.product-image')
                if product_links:
                    for tag in product_links:
                        href = tag.get('href')
                        if href:
                            full_url = urljoin(self.base_url, href)
                            all_product_links.add(full_url)
                    self.log_info(f"Collected {len(all_product_links)} total product links so far.")
                else:
                    self.log_info("No product links found on this page.")

                # Check for next page
                next_page_tag = soup.select_one('a.next')
                if next_page_tag and next_page_tag.get('href'):
                    next_href = next_page_tag.get('href')
                    current_url = urljoin(self.base_url, next_href)
                else:
                    self.log_info("No next page found. Ending scraping.")
                    break

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
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
                saved_path = await self.save_data(final_data)  # ✅ FIXED
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")
