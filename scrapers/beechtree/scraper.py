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
from utils.LoggerConstants import BEECHTREE_LOGGER
from urllib.parse import urljoin
from urllib.parse import urlsplit, urlunsplit, urljoin

import time


class Beechtree_Scrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://beechtree.pk/",
            logger_name=BEECHTREE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "beechtree"
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

            product_title_wrapper = soup.find('div', class_="product__title")
            if product_title_wrapper:
                try:
                    h1_tag = product_title_wrapper.find('h1')
                    if h1_tag:
                        product_data["title"] = h1_tag.get_text(strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product title: {e}")

            try:
                # SKU
                sku_element = soup.select_one('p.product__sku')
                if sku_element:
                    # Remove the visually hidden <span> text if present
                    sku_text = sku_element.get_text(strip=True).replace('SKU:', '').strip()
                    product_data['sku'] = sku_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's SKU: {e}")

            try:
                # === Prices Extraction ===
                price_wrapper = soup.find('div', class_='price--show-badge')
                if price_wrapper:
                    original_price_str = sale_price_str = ''

                    # Regular/original price (usually struck-through)
                    original_price_tag = price_wrapper.select_one('.price__sale s .money')
                    if not original_price_tag:
                        # Fallback if no <s> tag, get from .price__regular
                        original_price_tag = price_wrapper.select_one('.price__regular .money')

                    if original_price_tag:
                        original_price_str = original_price_tag.get_text(strip=True)
                        product_data['original_price'] = re.sub(r'[^\d.,]', '', original_price_str).lstrip('.')
                    else:
                        product_data['original_price'] = None

                    # Sale price (if available)
                    sale_price_tag = price_wrapper.select_one('.price__sale .price-item--sale .money')
                    if sale_price_tag:
                        sale_price_str = sale_price_tag.get_text(strip=True)
                        product_data['sale_price'] = re.sub(r'[^\d.,]', '', sale_price_str).lstrip('.')
                    else:
                        product_data['sale_price'] = None

                    # Extract currency from either price
                    currency_source = original_price_str or sale_price_str or ''
                    currency_match = re.search(r'(PKR|Rs|₹|\$|€|£)', currency_source)
                    product_data['currency'] = currency_match.group(1) if currency_match else None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")

            try:
                media_wrapper = soup.find('div', class_='new_product_media_inner')
                if media_wrapper:
                    # Find all <img> tags inside the swiper-slide elements
                    image_tags = media_wrapper.select('.swiper-slide img')

                    for img in image_tags:
                        src = img.get('src')
                        if src:
                            # Fix protocol-relative URLs starting with //
                            if src.startswith('//'):
                                src = 'https:' + src
                            # Join relative URLs with base URL
                            full_url = urljoin(self.base_url, src)
                            if full_url not in product_data['images']:
                                product_data['images'].append(full_url)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")

            try:
                # Product Description
                description_div = soup.select_one('div.product__description.rte.quick-add-hidden.desktop')
                if description_div:
                    # Convert <br> tags to newline
                    for br in description_div.find_all('br'):
                        br.replace_with('\n')

                    # Extract list items and paragraphs
                    list_items = [li.get_text(strip=True) for li in description_div.find_all('li')]
                    paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]

                    # Combine all text parts
                    description_parts = list_items + paragraphs
                    product_data['description'] = '\n'.join(description_parts)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product description: {e}")

            try:
                variants = []

                # Container holding size options
                size_container = soup.select_one('div.new_options_container')

                if size_container:
                    size_inputs = size_container.find_all('input', {'type': 'radio'})

                    for input_tag in size_inputs:
                        size_value = input_tag.get('value')
                        if not size_value:
                            continue

                        # Check if input has class 'disabled'
                        input_classes = input_tag.get('class', [])
                        is_available = 'disabled' not in input_classes  # True if not disabled

                        # Add to variants list
                        variants.append({
                            "size": size_value,
                            "availability": is_available
                        })

                # Store in product_data
                product_data['variants'] = variants or None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product variants: {e}")

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}

        return product_data




    async def scrape_products_links(self, url):
            all_product_links = []
            page_number = 1

            # Strip URL fragment (e.g., #Pret)
            split_url = urlsplit(url)
            base_url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, split_url.query, ''))

            while True:
                try:
                    current_url = f"{base_url}?page={page_number}" if "page=" not in base_url else base_url
                    self.log_info(f"Scraping page {page_number}: {current_url}")

                    response = await self.async_make_request(current_url)
                    

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Select anchors linking to products via div.card_carousel
                    product_anchors = soup.select('a[href^="/products/"] > div.card_carousel')

                    if not product_anchors:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break

                    for carousel_div in product_anchors:
                        parent_anchor = carousel_div.find_parent('a', href=True)
                        if parent_anchor:
                            product_url = urljoin(self.base_url, parent_anchor['href'])
                            if product_url not in all_product_links:
                                all_product_links.append(product_url)

                    page_number += 1

                except Exception as e:
                    self.log_error(f"Error scraping page {page_number}: {e}")
                    break

            self.log_info(f"Collected total {len(all_product_links)} product link(s).")
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
