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
from utils.LoggerConstants import BINSAEED_LOGGER
from urllib.parse import urljoin, urlparse
import time


class BinSaeedScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://binsaeedfabric.com/",
            logger_name=BINSAEED_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "BinSaeed"
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

            try:
                # Find <h1> tag with class 'productView-title'
                product_title_tag = soup.find('h1', class_='productView-title')
                if product_title_tag:
                    # Find inner <a> tag and get its text
                    a_tag = product_title_tag.find('a')
                    if a_tag and a_tag.get_text(strip=True):
                        product_data["title"] = a_tag.get_text(strip=True)
                    else:
                        product_data["title"] = None
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None

            try:
                breadcrumbs = []
                # Find <nav> with class 'breadcrumb breadcrumb-left'
                breadcrumb_nav = soup.find('nav', class_='breadcrumb breadcrumb-left')
                if breadcrumb_nav:
                    # Find all <a> tags (for links) and <span> tags (for current page)
                    a_tags = breadcrumb_nav.find_all('a')
                    span_tags = breadcrumb_nav.find_all('span')

                    for a in a_tags:
                        crumb = a.get_text(strip=True)
                        breadcrumbs.append(crumb)

                    for span in span_tags:
                        # Exclude separators containing <svg>
                        if not span.find('svg'):
                            crumb = span.get_text(strip=True)
                            if crumb:
                                breadcrumbs.append(crumb)

                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []


            try:
                category = []

                # Find <nav> with class 'breadcrumb breadcrumb-left'
                breadcrumb_nav = soup.find('nav', class_='breadcrumb breadcrumb-left')
                if breadcrumb_nav:
                    # Loop through direct children inside the breadcrumb nav
                    for child in breadcrumb_nav.children:
                        # Skip if not a tag
                        if not hasattr(child, 'get_text'):
                            continue

                        # Skip <a> tags with text 'Home'
                        if child.name == 'a':
                            crumb_text = child.get_text(strip=True)
                            if crumb_text.lower() == 'home':
                                continue
                            else:
                                category.append(crumb_text)

                        # If <span> tag, check if it contains visible text (ignore svg separators or empty spans)
                        elif child.name == 'span':
                            # Check if it has direct text
                            crumb_text = child.get_text(strip=True)
                            if crumb_text:
                                category.append(crumb_text)

                product_data['category'] = category

            except Exception as e:
                product_data['category'] = []
                print(f"Error scraping category breadcrumbs: {e}")


            try:
                # Find <div> with class 'price price--medium'
                price_div = soup.find('div', class_='price price--medium')

                if price_div:
                    # Extract regular and sale prices
                    regular_price_tag = price_div.find('span', class_='price-item--regular')
                    sale_price_tag = price_div.find('span', class_='price-item--sale')

                    def extract_price(text):
                        text = text.replace("From", "").strip()
                        currency_match = re.match(r'^(\D+)', text)
                        currency = currency_match.group(1).strip() if currency_match else None

                        if currency:
                            text = text.replace(currency, "", 1).strip()

                        text = text.replace(",", "")
                        price = re.sub(r'^[^\d]*', '', text)

                        return price, currency

                    # Initialize placeholders
                    original = None
                    sale = None
                    currency = None

                    # Extract regular price
                    if regular_price_tag:
                        regular_text = regular_price_tag.get_text(strip=True)
                        original, currency = extract_price(regular_text)

                    # Extract sale price
                    if sale_price_tag:
                        sale_text = sale_price_tag.get_text(strip=True)
                        sale, currency_sale = extract_price(sale_text)

                        # If sale price is same as original, set sale to None
                        if sale == original:
                            sale = None

                        # Use currency from sale if regular currency is None
                        if not currency and currency_sale:
                            currency = currency_sale

                    # If only sale price exists (no regular price)
                    if not original and sale:
                        original = sale
                        sale = None

                    product_data["original_price"] = original
                    product_data["sale_price"] = sale
                    product_data["currency"] = currency

                else:
                    product_data["original_price"] = None
                    product_data["sale_price"] = None
                    product_data["currency"] = None

            except Exception as e:
                product_data["original_price"] = None
                product_data["sale_price"] = None
                product_data["currency"] = None
                print(f"Error extracting price data: {e}")


            try:
                # ---------- Scrape SKU and Availability ----------
                sku_text = None
                availability_text = None

                # Find all <div> with class 'productView-info-item'
                sku_divs = soup.find_all('div', class_='productView-info-item')

                for div in sku_divs:
                    name_span = div.find('span', class_='productView-info-name')
                    value_span = div.find('span', class_='productView-info-value')

                    if name_span and value_span:
                        name = name_span.get_text(strip=True).lower()

                        if 'sku' in name:
                            sku_text = value_span.get_text(strip=True)

                        if 'availability' in name:
                            availability_raw = value_span.get_text(strip=True).lower()
                            availability_text = True if 'in stock' in availability_raw else None

                # Save to product_data
                product_data['sku'] = sku_text
                product_data['availability'] = availability_text

            except Exception as e:
                product_data['sku'] = None
                product_data['availability'] = None
                self.log_debug(f"Exception occurred while scraping SKU and availability: {e}")




            variants = []
            try:
                sizes = []
                # Find <fieldset> with the specific class
                size_fieldset = soup.find('fieldset', class_='js product-form__input clearfix')
                if size_fieldset:
                    # Find all input tags
                    input_tags = size_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in input_tags:
                        size_value = input_tag.get('value', '').strip()

                        # Find the corresponding label using 'for' attribute matching input's id
                        input_id = input_tag.get('id', '')
                        label_tag = size_fieldset.find('label', {'for': input_id})

                        if size_value and label_tag:
                            label_classes = label_tag.get('class', [])
                            availability = 'unavailable' if 'soldout' in label_classes else 'available'
                            sizes.append({
                                'size': size_value,
                                'availability': availability,
                            })
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes: {e}")

            colors = [{'availability': 'available'}]

            for size in sizes:
                combined_availability = 'false' if size['availability'] == 'unavailable' else 'true'
                variants.append({
                    'size': size['size'],
                    'availability': combined_availability,
                })

            product_data['variants'] = variants
         
            try:
                product_images = []

                # Find all <img> tags on the page
                img_tags = soup.find_all('img')
                for img_tag in img_tags:
                    src_img_url = img_tag.get('src')

                    if src_img_url:
                        # Check if '_medium.jpg' is in src to ensure only these images are scraped
                        if '_medium.jpg' in src_img_url:
                            # Convert URLs starting with '//' to 'https://'
                            if src_img_url.startswith('//'):
                                src_img_url = 'https:' + src_img_url

                            # Optional: Replace '_medium' with '' to get high-quality image if needed
                            high_quality_url = src_img_url.replace('_medium', '')

                            product_images.append(high_quality_url)

                # Remove duplicates
                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []


            try:
                description_text = ""

                # Find <div> with class 'productView-desc halo-text-format'
                desc_div = soup.find('div', class_='productView-desc halo-text-format')
                if desc_div:
                    # Extract text and strip it
                    description_text = desc_div.get_text(strip=True)

                product_data['description'] = description_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""


        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data



    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Select <a> tags with class 'card-media'
                product_links = soup.select('a.card-media')

                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                # Extract and add product URLs
                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Pagination: look for next page link (update selector as per your site's pagination)
                next_page_link = soup.select_one('a.next')  # Adjust if your pagination class is different
                if next_page_link:
                    next_href = next_page_link.get('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                        continue
                    else:
                        self.log_info("Next page href not found. Stopping pagination.")
                        break
                else:
                    self.log_info("No next page link found. Finished scraping all pages.")
                    break

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
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
