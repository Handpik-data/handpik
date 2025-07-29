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
from utils.LoggerConstants import MAKEUPCITY_LOGGER
from urllib.parse import urljoin
import time


class makeupcityscrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.makeupcityshop.com/",
            logger_name=MAKEUPCITY_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "makeupcity"
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
                title_tag = soup.select_one('h1.product-title span')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting product name: {str(e)}', 'product_link': product_link}
            
            try:
                # SKU
                sku_element = soup.select_one('div.sku-product span')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting SKU: {str(e)}', 'product_link': product_link}

            try:
                prices_div = soup.find('div', class_='prices')
                if prices_div:
                    # Extract sale price
                    sale_price_span = prices_div.find('span', class_='price', itemprop='price')
                    sale_price_text = sale_price_span.get_text(strip=True) if sale_price_span else None

                    # Extract original/compare price
                    compare_price_span = prices_div.find('span', class_='compare-price')
                    original_price_text = compare_price_span.get_text(strip=True) if compare_price_span else None

                    # Extract currency (e.g., Rs., $, etc.) from sale price
                    currency = None
                    currency_pattern = re.compile(r'^([^\d\s]+\.?)')  # e.g., matches Rs. or $
                    price_reference = sale_price_text or original_price_text
                    if price_reference:
                        currency_match = currency_pattern.match(price_reference)
                        currency = currency_match.group(1).strip() if currency_match else None

                    # Clean the price by removing currency, keeping commas and decimals
                    def clean_price(text):
                        if not text:
                            return None
                        return re.sub(r'^[^\d]+', '', text).strip()

                    # Apply logic: if no compare price, treat sale as original
                    if not original_price_text:
                        product_data['original_price'] = clean_price(sale_price_text)
                        product_data['sale_price'] = None
                    else:
                        product_data['original_price'] = clean_price(original_price_text)
                        product_data['sale_price'] = clean_price(sale_price_text)

                    product_data['currency'] = currency

            except Exception as e:
                return {'error': f'Exception occurred while extracting prices: {str(e)}', 'product_link': product_link}

            try:
                # Extract breadcrumbs and save to attributes
                breadcrumb_div = soup.find('div', class_='breadcrumb')
                if breadcrumb_div:
                    crumbs = breadcrumb_div.find_all(['a', 'span'])
                    breadcrumb_texts = []

                    for crumb in crumbs:
                        # If <span> contains an <a>, extract the <a> text
                        a_tag = crumb.find('a')
                        if a_tag:
                            text = a_tag.get_text(strip=True)
                        else:
                            text = crumb.get_text(strip=True)

                        if text and text != '›':  # Exclude arrow symbols if present as text
                            breadcrumb_texts.append(text)

                    product_data.setdefault('attributes', {})['breadcrumbs'] = breadcrumb_texts

            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}

            try:
                # Images
                image_elements = soup.find_all('a', class_='fancybox', href=True)
                for a_tag in image_elements:
                    href = a_tag.get('href')
                    if 'cdn/shop/' in href:
                        if href.startswith('//'):
                            href = 'https:' + href
                        else:
                            href = urljoin(self.base_url, href)
                        if href not in product_data['images']:
                            product_data['images'].append(href)
            except Exception as e:
                return {'error': f'Exception occurred while extracting images: {str(e)}', 'product_link': product_link}

            try:
                # Description extraction for your provided tag structure
                desc_div = soup.select_one('div#collapse-tab1 > div')
                if desc_div:
                    description = desc_div.get_text(' ', strip=True).replace('\xa0', ' ').replace('  ', ' ')
                    product_data['description'] = description
            except Exception as e:
                return {'error': f'Exception occurred while extracting description: {str(e)}', 'product_link': product_link}

            try:
                # Extract category trail from breadcrumb div
                breadcrumb_div = soup.find('div', class_='breadcrumb')
                if breadcrumb_div:
                    breadcrumb_items = []

                    # Find all direct children: <a> and <span> tags in order
                    for child in breadcrumb_div.find_all(['a', 'span'], recursive=False):
                        # Skip the Home link
                        if child.name == 'a' and 'data-translate' in child.attrs and child['data-translate'] == 'general.breadcrumbs.home':
                            continue

                        text = child.get_text(strip=True)
                        if text:  # Ignore empty spans
                            breadcrumb_items.append(text)

                    if breadcrumb_items:
                        # Save as a list
                        product_data['category'] = breadcrumb_items

            except Exception as e:
                return {'error': f'Exception occurred while extracting category from breadcrumb: {str(e)}', 'product_link': product_link}

            try:
                # Find the jdgm preview badge div
                preview_badge = soup.find('div', class_='jdgm-prev-badge')
                
                if preview_badge:
                    # Extract number of reviews
                    num_reviews = preview_badge.get('data-number-of-reviews', None)
                    
                    # Extract average star rating
                    avg_rating = preview_badge.get('data-average-rating', None)
                    
                    # Save to product_data
                    product_data['raw_data']['total_reviews'] = int(num_reviews) if num_reviews else 0
                    product_data['raw_data']['average_rating'] = float(avg_rating) if avg_rating else 0.0

                else:
                    product_data['raw_data']['total_reviews'] = 0
                    product_data['raw_data']['average_rating'] = 0.0

            except Exception as e:
                return {'error': f'Exception occurred while extracting preview badge reviews: {str(e)}', 'product_link': product_link}

                    
            try:
                # Extract Sizes and Availability
                fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
                if fieldset:
                    inputs = fieldset.find_all('input', {'class': 'product-form__radio'})
                    for input_tag in inputs:
                        size = input_tag.get('value')
                        input_id = input_tag.get('id')
                        label = fieldset.find('label', {'for': input_id})

                        # Check availability class
                        availability = True if label and 'available' in label.get('class', []) else False

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

                # Find all divs with class 'inner-top'
                inner_top_divs = soup.find_all('div', class_='inner-top')

                if not inner_top_divs:
                    self.log_info(f"No 'inner-top' divs found on page {page_number}. Stopping.")
                    break

                new_links_found = False

                for div in inner_top_divs:
                    # Within each inner-top div, find the <a> tag with desired product href
                    link_tag = div.select_one('a.product-grid-image.adaptive_height[href*="/products/"]')
                    if link_tag:
                        href = link_tag.get('href')
                        if href:
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