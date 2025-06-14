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
from utils.LoggerConstants import ALKARAM_LOGGER
from urllib.parse import urljoin
import time


class AlkaramScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://www.alkaramstudio.com/",
            logger_name=ALKARAM_LOGGER
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
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'currency': None,
                'images': [],
                'description': {},
                'attributes': {},
                'product_link': product_link,
                'variants': []  # Initialize variants as empty list
            }

            # Title
            title_tag = soup.select_one('h1.t4s-product__title')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)

            # SKU
            sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)
          
            # Pricing
            price_div = soup.find('div', class_='t4s-product-price')
            original_price = sale_price = save_percent = currency = None

            if price_div:
                price_text = price_div.get_text(strip=True)
                
                # Extract currency symbol (assuming it's at the start of the price)
                currency_match = re.match(r'^([^\d\s]+)', price_text)
                if currency_match:
                    currency = currency_match.group(1)
                
                # Extract sale price text
                sale_price = price_text
                
                # Extract original price from data attribute
                data_price = price_div.get('data-price')
                if data_price:
                    original_price = f"{currency if currency else 'PKR'} {int(data_price) // 100:,}"

            product_data['original_price'] = original_price
            product_data['sale_price'] = sale_price
            product_data['currency'] = currency  # Store the currency separately
            # Images
            image_elements = soup.select('img[data-master]')
            for img in image_elements:
                src = img.get('data-master')
                if src and src not in product_data['images']:
                    full_url = urljoin(self.base_url, src)
                    product_data['images'].append(full_url)

            # Stock Availability
            time.sleep(2)
            stock_element = soup.select_one('p.t4s-inventory_message')
            if stock_element:
                stock_count = stock_element.select_one('span.t4s-count')
                if stock_count:
                    stock_text = stock_count.get_text(strip=True)
                    if stock_text.isdigit():
                        product_data['stock'] = int(stock_text)
                    else:
                        product_data['stock'] = None
                else:
                    product_data['stock'] = None
            else:
                product_data['stock'] = None

            # Inside your scrape_pdp function where you handle variants:

            # Variants (Sizes)
            size_container = soup.find('div', {'class': 't4s-swatch__list'})
            if size_container:
                size_elements = size_container.find_all('div', {'data-swatch-item': ''})
                
                for size_element in size_elements:
                    size_value = size_element.get_text(strip=True)
                    
                    # Determine availability - True if available, False if sold out
                    is_available = 'is--soldout' not in size_element.get('class', [])
                    
                    variant_data = {
                        'size': size_value,
                        'available': is_available  # Simple True/False for availability
                    }
                    
                    product_data['variants'].append(variant_data)

            # Details
            details_div = soup.select_one('div.t4s-rte.t4s-tab-content.t4s-active')
            if details_div:
                disclaimer = details_div.select_one('div.tab--disclaimer')
                if disclaimer:
                    disclaimer.decompose()

                for br in details_div.find_all('br'):
                    br.replace_with('\n')

                raw_text = details_div.get_text(separator='\n').strip()
                lines = [line.strip().replace('\xa0', ' ') for line in raw_text.split('\n') if line.strip()]

                details = {}
                current_key = None

                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip()
                        value = value.strip()
                        details[key] = value
                        current_key = key
                    elif current_key:
                        details[current_key] += f" {line}"
                    else:
                        details[line] = None

                product_data['attributes'] = details

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}

    
    async def scrape_products_links(self, url):
            all_product_links = []
            page_number = 1
            current_url = url

            while True:
                try:
                    self.log_info(f"Scraping page {page_number}: {current_url}")
                    response = requests.get(current_url, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')
                    product_links = soup.select('a.t4s-full-width-link')

                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break

                    for link_tag in product_links:
                        href = link_tag.get('href')
                        if href:
                            product_url = f"{self.base_url}{href}"
                            all_product_links.append(product_url)

                    page_number += 1
                    current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

                except Exception as e:
                    self.log_error(f"Error scraping page {page_number}: {e}")
                    break

            # Debug: Print the collected links
            self.log_info(f"Collected {len(all_product_links)} product links.")
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
