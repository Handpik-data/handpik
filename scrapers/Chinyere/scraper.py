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
from utils.LoggerConstants import CHINYERE_LOGGER
from urllib.parse import urljoin
import time


class chinyerescraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://www.chinyere.pk/",
            logger_name=CHINYERE_LOGGER
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
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'images': [],
                'product_description': None,
                'breadcrumbs': [],
                'product_link': product_link,
                'sizes': [],
            }

            # Product Name
            title_tag = soup.select_one('h1.productView-title')
            if title_tag:
                product_data['product_name'] = title_tag.get_text(strip=True)

            # Product Title / Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('div.productView-info-item span.productView-info-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)


            # Prices
            # Prices
            price_div = soup.find('div', class_='price')
            if price_div:
                # Try to find sale price (discounted price)
                sale_last_dd = price_div.select_one('div.price__sale dd.price__last span.money')
                if sale_last_dd:
                    product_data['sale_price'] = sale_last_dd.get_text(strip=True)

                # Try to find original (compare) price
                compare_dd = price_div.select_one('div.price__sale dd.price__compare span.money')
                if compare_dd:
                    product_data['original_price'] = compare_dd.get_text(strip=True)

                # If no sale section exists, fallback to regular price
                if 'sale_price' not in product_data:
                    regular_dd = price_div.select_one('div.price__regular dd.price__last span.money')
                    if regular_dd:
                        product_data['original_price'] = regular_dd.get_text(strip=True)

            # Color and SKU from style-id section
            style_id_div = soup.select_one('div.new-product-style-id.mobile-hide')
            if style_id_div:
                color_text = ''.join([t for t in style_id_div.contents if isinstance(t, str)]).strip().replace('|', '').strip()
                sku_span = style_id_div.find('span')
                if color_text:
                    product_data['attributes']['color'] = color_text
                if sku_span:
                    product_data['sku'] = sku_span.get_text(strip=True)

           # Initialize images list if not already present
            if 'images' not in product_data:
                product_data['images'] = []

            # Find all divs with class 'media' and having a 'data-fancybox' attribute set to "images"
            media_divs = soup.find_all('div', class_='media', attrs={'data-fancybox': 'images'})

            for media_div in media_divs:
                href = media_div.get('href')
                if href:
                    # Complete URL handling
                    if href.startswith('//'):
                        href = 'https:' + href
                    full_url = urljoin(self.base_url, href)
                    
                    # Avoid duplicates
                    if full_url not in product_data['images']:
                        product_data['images'].append(full_url)

            # Product Description
            description_div = soup.select_one('div#tab-description-mobile')
            if description_div:
                # Replace <br> tags with newlines
                for br in description_div.find_all('br'):
                    br.replace_with('\n')

                # Extract all <p> tags and clean the text
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]

                # Join paragraphs into a single string with double newlines
                product_data['product_description'] = '\n\n'.join(paragraphs)
            else:
                product_data['product_description'] = None

             # Sizes
            all_sizes = []
            visible_sizes = []

            # Select the fieldset that holds size options
            size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
            if size_fieldset:
                # Find all size input labels
                size_labels = size_fieldset.find_all('label', class_='product-form__label')
                for label in size_labels:
                    size_text = label.find('span', class_='text')
                    if size_text:
                        size_value = size_text.get_text(strip=True)
                        all_sizes.append(size_value)
                        visible_sizes.append(size_value)  # all listed sizes are visible in this structure

            product_data['all_sizes'] = all_sizes or None
            product_data['visible_sizes'] = visible_sizes or None

            # Initialize breadcrumbs list if not already present
            if 'breadcrumbs' not in product_data:
                product_data['breadcrumbs'] = []

            # Select all <a> and <span> elements inside <nav class="breadcrumb breadcrumb-left">
            breadcrumb_nav = soup.select_one('breadcrumb-component nav.breadcrumb.breadcrumb-left')

            if breadcrumb_nav:
                breadcrumb_items = breadcrumb_nav.select('a, span')
                for crumb in breadcrumb_items:
                    text = crumb.get_text(strip=True)
                    if text:
                        product_data['breadcrumbs'].append(text)


            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}
    
        
    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = requests.get(current_url, headers=self.headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')

                # Select all <a> tags with class 'card-link' and href starting with '/products/'
                link_tags = soup.select('a.card-link[href^="/products/"]')

                if not link_tags:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                initial_count = len(all_product_links)

                for link_tag in link_tags:
                    href = link_tag['href']
                    product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                    all_product_links.add(product_url)

                if len(all_product_links) == initial_count:
                    self.log_info("No new products found. Stopping.")
                    break

                page_number += 1
                if "?" not in url:
                    current_url = f"{url}?page={page_number}"
                else:
                    current_url = f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        self.log_info(f"Collected {len(all_product_links)} unique product links.")
        return list(all_product_links)

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
