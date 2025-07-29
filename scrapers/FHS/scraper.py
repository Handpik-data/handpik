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
from utils.LoggerConstants import FHS_LOGGER
from urllib.parse import urljoin
import time


class FHSscrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://fhsofficial.com/",
            logger_name=FHS_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "FHS"
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
            'raw_data': {},
        }
    
        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                # Product Name
                title_tag = soup.select_one('h1.product-title')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting product name: {str(e)}', 'product_link': product_link}

            
            try:
                # SKU
                sku_element = soup.select_one('div.sku_product span.variant-sku')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting SKU: {str(e)}', 'product_link': product_link}

            try:
                prices_div = soup.find('div', class_='product-price')
                if prices_div:
                    # Extract original price (if exists)
                    original_price_span = prices_div.find('span', class_='price-item--regular')
                    original_price_text = original_price_span.get_text(strip=True) if original_price_span else None

                    # Extract sale price (if exists)
                    sale_price_span = prices_div.find('span', class_='price-item--sale')
                    sale_price_text = sale_price_span.get_text(strip=True) if sale_price_span else None

                    # Extract currency using regex (e.g., Rs., $, AED)
                    currency_pattern = re.compile(r'^([^\d\s]+\.?)')  # Matches "Rs.", "$", etc.
                    currency = None
                    price_reference = sale_price_text or original_price_text

                    if price_reference:
                        currency_match = currency_pattern.match(price_reference)
                        currency = currency_match.group(1).strip() if currency_match else None

                    # Clean price text to remove currency only — keep commas and decimals
                    def clean_price(text):
                        if not text:
                            return None
                        return re.sub(r'^[^\d]+', '', text).strip()

                    product_data['original_price'] = clean_price(original_price_text)
                    product_data['sale_price'] = clean_price(sale_price_text) if sale_price_text else None
                    product_data['currency'] = currency

            except Exception as e:
                return {'error': f'Exception occurred while extracting prices: {str(e)}', 'product_link': product_link}

            try:
                # Extract breadcrumbs and save to attributes
                breadcrumb_div = soup.find('div', class_='breadcrumb-content')
                if breadcrumb_div:
                    crumbs = breadcrumb_div.find_all(['a', 'span'])
                    breadcrumb_texts = []

                    for crumb in crumbs:
                        # Check if <span> contains an <a> tag
                        a_tag = crumb.find('a')
                        if a_tag:
                            text = a_tag.get_text(strip=True)
                        else:
                            # For spans without <a> or direct <a> tags
                            text = crumb.get_text(strip=True)

                        # Exclude arrow symbols and empty texts
                        if text and text != '›':
                            breadcrumb_texts.append(text)

                    product_data.setdefault('attributes', {})['breadcrumbs'] = breadcrumb_texts

            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}
        
            try:
                # Images
                image_elements = soup.find_all('img', class_='product-featured-img')
                for img_tag in image_elements:
                    src = img_tag.get('src')
                    if src:
                        if 'cdn/shop/' in src:
                            if src.startswith('//'):
                                src = 'https:' + src
                            else:
                                src = urljoin(self.base_url, src)
                            if src not in product_data['images']:
                                product_data['images'].append(src)
            except Exception as e:
                return {'error': f'Exception occurred while extracting images: {str(e)}', 'product_link': product_link}

            try:
                # Description extraction for the updated tag structure
                desc_div = soup.select_one('div.tab-description div#collapse-tab1 > div')
                if desc_div:
                    # Extract all <p> tags within the div and join with line breaks or spaces as needed
                    paragraphs = desc_div.find_all('p')
                    description_texts = [p.get_text(' ', strip=True).replace('\xa0', ' ') for p in paragraphs]
                    description = ' '.join(description_texts).replace('  ', ' ')
                    product_data['description'] = description
            except Exception as e:
                return {'error': f'Exception occurred while extracting description: {str(e)}', 'product_link': product_link}

            try:
                # Extract category trail from breadcrumb-content div
                breadcrumb_div = soup.select_one('div.breadcrumb-content')
                if breadcrumb_div:
                    breadcrumb_items = []

                    # Find all <a> and <span> elements in order
                    crumbs = breadcrumb_div.find_all(['a', 'span'])
                    for crumb in crumbs:
                        # Skip "Home" link based on data-translate attribute
                        if crumb.name == 'a' and crumb.get('data-translate') == 'general.breadcrumbs.home':
                            continue

                        # If <span> contains an <a>, extract that <a> text
                        a_tag = crumb.find('a')
                        if a_tag:
                            text = a_tag.get_text(strip=True)
                        else:
                            text = crumb.get_text(strip=True)

                        # Skip arrow symbols and empty texts
                        if text and text != '›':
                            breadcrumb_items.append(text)

                    if breadcrumb_items:
                        product_data['category'] = breadcrumb_items

            except Exception as e:
                return {'error': f'Exception occurred while extracting category from breadcrumb: {str(e)}', 'product_link': product_link}
            


            try:
                # Extract availability
                availability_div = soup.find('div', class_='product_inventory')
                if availability_div:
                    text = availability_div.get_text(strip=True).lower()
                    availability = 'in stock' in text
                    product_data['availability'] = availability
            except Exception as e:
                return {'error': f'Exception occurred while extracting availability: {str(e)}', 'product_link': product_link}

            try:
                # Extract Sizes and Availability
                product_data['variants'] = []
                
                # Find all swatch-element divs under the form
                swatch_elements = soup.find_all('div', class_='swatch-element')
                for swatch in swatch_elements:
                    input_tag = swatch.find('input')
                    label_tag = swatch.find('label')

                    if input_tag and label_tag:
                        size = input_tag.get('value')

                        # Determine availability
                        is_disabled = input_tag.has_attr('disabled')
                        has_soldout_class = 'soldout' in swatch.get('class', [])
                        availability = not (is_disabled or has_soldout_class)

                        product_data['variants'].append({
                            'size': size,
                            'availability': availability
                        })

            except Exception as e:
                return {'error': f'Exception occurred while extracting sizes and availability: {str(e)}', 'product_link': product_link}

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

                # Find all <a> tags with class 'product-link image-swap' and href containing '/products/'
                product_links = soup.find_all('a', class_='product-link image-swap', href=True)

                if not product_links:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                new_links_found = False

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href and '/products/' in href:
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)
                            new_links_found = True

                if not new_links_found:
                    self.log_info(f"No new product links found on page {page_number}. Stopping.")
                    break  # Stop if no new links were added

                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

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