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
            'title': None,
            'original_price': None,
            'sale_price': None,
            'currency':None,
            'images': [],
            'description': None,
            'product_link': product_link,
            'variants':None
        }

            # Product Name
            product_name = None
            title_div = soup.select_one('div.product__title')

            if title_div:
                h1_tag = title_div.find('h1')
                if h1_tag:
                    product_name = h1_tag.get_text(strip=True)

            if product_name:
                product_data['title'] = product_name

            
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

                    # Extract currency from whichever price is available
                    if original_price_str and ' ' in original_price_str:
                        product_data['currency'] = original_price_str.split()[0]
                    elif sale_price_str and ' ' in sale_price_str:
                        product_data['currency'] = sale_price_str.split()[0]
                    else:
                        product_data['currency'] = None

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
                product_data['description'] = '\n'.join(description_parts)
                
                                
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
                        is_disabled = 'disabled' in input_classes
                        availability = 'Unavailable' if is_disabled else 'Available'

                        # Add to variants list
                        variants.append({
                            "size": size_value,
                            "availability": availability
                        })

                # Store in product_data
                product_data['variants'] = variants or None

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}
    


    async def scrape_products_links(self, url):
        all_product_links = []

        # Strip URL fragment (like #Pret)
        split_url = urlsplit(url)
        url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, split_url.query, ''))

        try:
            self.log_info(f"Scraping page 1: {url}")
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Select anchors linking to products via div.card_carousel
            product_anchors = soup.select('a[href^="/products/"] > div.card_carousel')

            if not product_anchors:
                self.log_info("No product links found on the first page.")
                return []

            for carousel_div in product_anchors:
                parent_anchor = carousel_div.find_parent('a', href=True)
                if parent_anchor:
                    product_url = urljoin(self.base_url, parent_anchor['href'])
                    if product_url not in all_product_links:
                        all_product_links.append(product_url)

        except Exception as e:
            self.log_error(f"Error scraping page: {e}")

        self.log_info(f"Collected {len(all_product_links)} product link(s).")
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
