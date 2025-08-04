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
from utils.LoggerConstants import HopScotch_LOGGER
from urllib.parse import urljoin, urlparse
import time


class HopscotchScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://ilovehopscotch.com/",
            logger_name=HopScotch_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )   
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Hopsoctch"
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
                product_title_tag = soup.find('h1', class_='t4s-product__title')
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception while scraping title: {e}")

            # 🔹 Scrape SKU
            try:
                sku_div = soup.find('div', class_='t4s-sku-wrapper')
                if sku_div:
                    sku_span = sku_div.find('span', class_='t4s-productMeta__value t4s-sku-value t4s-csecondary')
                    if sku_span:
                        product_data['sku'] = sku_span.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception while scraping SKU: {e}")

            # 🔹 Scrape Breadcrumbs
            try:
                breadcrumbs = []
                breadcrumb_nav = soup.find('nav', class_='t4s-pr-breadcrumb')
                if breadcrumb_nav:
                    a_tags = breadcrumb_nav.find_all('a')
                    for a_tag in a_tags:
                        crumb = a_tag.get_text(strip=True)
                        if crumb:
                            breadcrumbs.append(crumb)
                    span_tag = breadcrumb_nav.find('span')
                    if span_tag:
                        crumb = span_tag.get_text(strip=True)
                        if crumb:
                            breadcrumbs.append(crumb)
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception while scraping breadcrumbs: {e}")

            # 🔹 Scrape Price
            try:
                def extract_price(text):
                    text = text.strip()
                    currency_match = re.match(r'^([^\d]+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price_match = re.search(r'(\d[\d,\.]*)', text)
                    price = price_match.group(1).replace(",", "") if price_match else None
                    return price, currency

                price_container = soup.find('div', class_='t4s-product-price')
                if price_container:
                    del_tag = price_container.find('del')
                    if del_tag:
                        original_text = del_tag.get_text(strip=True)
                        original_price, currency = extract_price(original_text)
                        product_data['original_price'] = original_price
                        product_data['currency'] = currency

                    ins_tag = price_container.find('ins')
                    if ins_tag:
                        sale_text = ins_tag.get_text(strip=True)
                        sale_price, currency = extract_price(sale_text)
                        product_data['sale_price'] = sale_price
                        if not product_data['currency']:
                            product_data['currency'] = currency
            except Exception as e:
                self.log_debug(f"Exception while scraping price: {e}")

            # 🔹 Scrape Category
            try:
                categories = []
                breadcrumb_nav = soup.find('nav', class_='t4s-pr-breadcrumb')
                if breadcrumb_nav:
                    a_tags = breadcrumb_nav.find_all('a')
                    for a in a_tags:
                        text = a.get_text(strip=True)
                        if text and text != "Home":
                            categories.append(text)
                    span_tag = breadcrumb_nav.find('span')
                    if span_tag:
                        text = span_tag.get_text(strip=True)
                        if text:
                            categories.append(text)
                product_data["category"] = categories
            except Exception as e:
                self.log_debug(f"Exception while scraping categories: {e}")

            # 🔹 Scrape Images
            try:
                images_set = set()
                seen_basenames = set()

                divs = soup.find_all('div', class_='t4s_ratio t4s-product__media is-pswp-disable')
                for div in divs:
                    img_tags = div.find_all('img')
                    for img in img_tags:
                        img_url = None

                        # Priority: data-master → data-srcset → data-src → src
                        data_master = img.get('data-master')
                        if data_master:
                            img_url = data_master

                        if not img_url:
                            data_srcset = img.get('data-srcset')
                            if data_srcset:
                                srcset_items = [item.strip() for item in data_srcset.split(',')]
                                if srcset_items:
                                    last_item = srcset_items[-1]
                                    parts = last_item.split(' ')
                                    if parts:
                                        img_url = parts[0]

                        if not img_url:
                            data_src = img.get('data-src')
                            if data_src:
                                img_url = data_src

                        if not img_url:
                            src = img.get('src')
                            if src and not src.startswith('data:image'):
                                img_url = src

                        # Normalize the URL
                        if img_url:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            elif img_url.startswith('/'):
                                img_url = 'https://ilovehopscotch.com' + img_url

                            # Remove width query param for high-quality and deduplication
                            base_url = img_url.split('&width=')[0]

                            if base_url not in seen_basenames:
                                seen_basenames.add(base_url)
                                images_set.add(base_url)

                product_data['images'] = list(images_set)
            except Exception as e:
                self.log_debug(f"Exception while scraping images: {e}")


       # 🔹 Scrape Variants (Sizes, Color, Availability)
            try:
                sizes = []
                size_divs = soup.find_all('div', attrs={'data-swatch-item': True})
                for div in size_divs:
                    size = div.get('data-value')
                    if size:
                        sizes.append(size.strip())

                # 🔹 Extract color
                color = None
                color_div = soup.find('div', class_='t4s-swatch__list')
                if color_div:
                    selected_color = color_div.find('div', class_='is--selected')
                    if selected_color:
                        color = selected_color.get('data-value')
                    else:
                        first_color = color_div.find('div')
                        if first_color:
                            color = first_color.get('data-value')

                # 🔹 Remove color value from sizes if present
                sizes = [s for s in sizes if s != color]

                # 🔹 Extract availability
                size_dropdown = soup.find('div', attrs={'data-sticky-select': True})
                availability_list = []
                if size_dropdown:
                    buttons = size_dropdown.find_all('button', attrs={'data-dropdown-item': True})
                    for button in buttons:
                        availability = not button.has_attr('disabled')
                        availability_list.append(availability)

                # 🔹 Combine sizes with availability and color
                min_len = min(len(sizes), len(availability_list))
                variants = []
                for i in range(min_len):
                    variant = {
                        "size": sizes[i],
                        "color": color if color else None,
                        "availability": availability_list[i]
                    }
                    variants.append(variant)

                # 🔹 Save to product_data
                product_data['variants'] = variants

            except Exception as e:
                self.log_debug(f"Exception while scraping variants: {e}")
                product_data['variants'] = []

            # 🔹 Scrape Description
            try:
                description_text = ""
                desc_div = soup.find('div', class_='t4s-product__description t4s-rte')
                if desc_div:
                    paragraphs = desc_div.find_all('p')
                    desc_lines = []
                    for p in paragraphs:
                        line = p.get_text(separator=" ", strip=True)
                        if line:
                            desc_lines.append(line)
                    description_text = " ".join(desc_lines).strip()
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception while scraping description: {e}")
                product_data['description'] = ""

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data


 
    async def scrape_products_links(self, url):
        all_product_links = []

        try:
            # Ensure URL ends with '/'
            if not url.endswith('/'):
                url += '/'

            json_url = url + 'products.json'
            self.log_info(f"Scraping: {json_url}")

            response = requests.get(json_url, timeout=10)
            response.raise_for_status()

            data = response.json()
            products = data.get('products', [])

            if not products:
                self.log_info("No product links found in JSON. Stopping.")
            else:
                for product in products:
                    handle = product.get('handle')
                    if handle:
                        product_url = urljoin(self.base_url, f'/products/{handle}')
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links from JSON endpoint.")

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
