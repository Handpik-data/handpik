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
    def __init__(self):
        super().__init__(
            base_url="https://beechtree.pk/",
            logger_name=BEECHTREE_LOGGER
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        filepath = os.path.join(self.module_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filepath, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))


    async def scrape_pdp(self, product_link):
        try:
            response = requests.get(product_link)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
            'product_name': None,
            'product_title': None,
            'original_price': None,
            'sale_price': None,
            'save_percent': None,
            'images': [],
            'product_description': None,
            'product_link': product_link,
            'sizes': [],
        }

            # Product Name
            product_name = None
            title_div = soup.select_one('div.product__title')

            if title_div:
                h1_tag = title_div.find('h1')
                if h1_tag:
                    product_name = h1_tag.get_text(strip=True)

            if product_name:
                product_data['product_name'] = product_name

            # Product Title / Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('p.product__sku')
            if sku_element:
                # Remove the visually hidden <span> text if present
                sku_text = sku_element.get_text(strip=True).replace('SKU:', '').strip()
                product_data['sku'] = sku_text


                # Prices
                price_wrapper = soup.find('div', class_='price--show-badge')
                if price_wrapper:
                    # Regular/original price (usually struck-through)
                    original_price_tag = price_wrapper.select_one('.price__sale s .money')
                    if not original_price_tag:
                        # Fallback if no <s> tag, get from .price__regular
                        original_price_tag = price_wrapper.select_one('.price__regular .money')

                    if original_price_tag:
                        original_price_str = original_price_tag.get_text(strip=True)
                        product_data['original_price'] = original_price_str
                    else:
                        original_price_str = None
                        product_data['original_price'] = None

                    # Sale price (if available)
                    sale_price_tag = price_wrapper.select_one('.price__sale .price-item--sale .money')
                    if sale_price_tag:
                        sale_price_str = sale_price_tag.get_text(strip=True)
                        product_data['sale_price'] = sale_price_str
                    else:
                        sale_price_str = None
                        product_data['sale_price'] = None

                    # Helper to parse price string like 'PKR 2,232' to float
                    def parse_price(price_str):
                        if not price_str:
                            return None
                        return float(price_str.replace('PKR', '').replace(',', '').strip())

                    original_price = parse_price(original_price_str)
                    sale_price = parse_price(sale_price_str)

                    # Determine save_percent
                    if original_price is not None and sale_price is not None and sale_price < original_price:
                        saved_percent = ((original_price - sale_price) / original_price) * 100
                        product_data['save_percent'] = f"{saved_percent:.0f} % off"
                    else:
                        # Check if discount badge exists
                        discount_badge = soup.select_one('.bt-sale-badge')
                        if discount_badge:
                            percent_text = discount_badge.get_text(strip=True)
                            if percent_text.startswith('-') and percent_text.endswith('%'):
                                product_data['save_percent'] = percent_text.replace('-', '') + " off"
                            else:
                                product_data['save_percent'] = None
                        else:
                            product_data['save_percent'] = None

                        # If no valid sale, force sale_price to None
                        product_data['sale_price'] = None


                    # Find the container with image slides
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
                product_data['product_description'] = '\n'.join(description_parts)

            all_sizes = []
            visible_sizes = []

            # Find the fieldset for sizes
            size_fieldset = soup.select_one('fieldset.product-form__input--pill.size')

            if size_fieldset:
                # Find all <input type="radio"> inside that fieldset
                size_inputs = size_fieldset.find_all('input', {'type': 'radio'})
                for input_tag in size_inputs:
                    size_value = input_tag.get('value')
                    if size_value:
                        all_sizes.append(size_value)
                        
                        # Check if input is NOT disabled attribute
                        if not input_tag.has_attr('disabled'):
                            visible_sizes.append(size_value)

            product_data['all_sizes'] = all_sizes or None
            product_data['visible_sizes'] = visible_sizes or None


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

                # Select anchors linking to products via div.card_carousel
                product_anchors = soup.select('a[href^="/products/"] > div.card_carousel')

                if not product_anchors:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                for carousel_div in product_anchors:
                    parent_anchor = carousel_div.find_parent('a', href=True)
                    if parent_anchor:
                        product_url = urljoin(self.base_url, parent_anchor['href'])
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
        product_links = await self.scrape_products_links(url)

        for product_link in product_links:
            pdp_data = await self.scrape_pdp(product_link)
            if pdp_data and not pdp_data.get('error'):
                all_products.append(pdp_data)
            await asyncio.sleep(1)

        return all_products

    async def scrape_data(self):
        final_data = []
        try:
            category_urls = await self.get_unique_urls_from_file("categories.txt")

            for url in category_urls:
                self.log_info(f"Scraping category: {url}")
                category_data = await self.scrape_category(url)
                final_data.extend(category_data)

            if final_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                output_filename = f"products_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_filename)

                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)

                self.log_info(f"Saved {len(final_data)} products into {output_filename}")
            else:
                self.log_error("No products scraped.")

        except Exception as e:
            self.log_error(f"Error in scrape_data: {str(e)}")
