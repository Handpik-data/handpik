import os
import re
import json
import asyncio
from statistics import variance
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import DHANAK_LOGGER
from urllib.parse import urljoin
import time


class EthinicScrapper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://dhanak.com.pk/",
            logger_name=DHANAK_LOGGER
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
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(product_link) as response:
                    if response.status != 200:
                        self.log_error(f"Failed to get product page: {product_link} Status: {response.status}")
                        return {'error': 'Failed to fetch product page', 'product_link': product_link}
                    html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            product_data = {
                'title': None,
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'currency': None,
                'images': [],
                'description': None,
                'product_link': product_link,
                'variants': variance or None  # assign the parsed list or None if empty
            }

            # Product Name
            title_tag = soup.select_one('h1.productView-title')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)

            # SKU
            sku_element = soup.select_one('div.productView-info-item span.productView-info-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)
           
            # Prices
            price_div = soup.find('div', class_='price')
            if price_div:
                # Check for sale badge to determine if product is on sale
                sale_badge = soup.select_one('span.badge.sale-badge')
                is_on_sale = sale_badge is not None

                # Try to find sale price (discounted price)
                sale_price_span = price_div.select_one('div.price__sale dd.price__last span.price-item--sale')
                if not sale_price_span:  # Fallback to alternative selector
                    sale_price_span = price_div.select_one('div.price__sale dd.price__last span.price-item')

                if sale_price_span:
                    sale_price_text = sale_price_span.get_text(strip=True)
                    product_data['sale_price'] = sale_price_text

                    # Extract currency from sale price
                    currency_match = re.match(r'^(\D+)', sale_price_text)
                    if currency_match:
                        product_data['currency'] = currency_match.group(1).strip()

                # Try to find original (compare) price
                compare_price = price_div.select_one('div.price__sale dd.price__compare s.price-item--regular')
                if not compare_price:  # Fallback to alternative selector
                    compare_price = price_div.select_one('div.price__sale dd.price__compare s.price-item')

                if compare_price:
                    original_price_text = compare_price.get_text(strip=True)
                    product_data['original_price'] = original_price_text

                    # Extract currency if not already found
                    if 'currency' not in product_data:
                        currency_match = re.match(r'^(\D+)', original_price_text)
                        if currency_match:
                            product_data['currency'] = currency_match.group(1).strip()

                # If no sale section exists, fallback to regular price
                if 'sale_price' not in product_data:
                    regular_price = price_div.select_one('div.price__regular dd.price__last span.price-item--regular')
                    if not regular_price:  # Fallback to alternative selector
                        regular_price = price_div.select_one('div.price__regular dd.price__last span.price-item')

                    if regular_price:
                        regular_price_text = regular_price.get_text(strip=True)
                        product_data['original_price'] = regular_price_text

                        # Extract currency if not already found
                        if 'currency' not in product_data:
                            currency_match = re.match(r'^(\D+)', regular_price_text)
                            if currency_match:
                                product_data['currency'] = currency_match.group(1).strip()

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
                product_data['description'] = '\n\n'.join(paragraphs)
            else:
                product_data['description'] = None

              
            
            
            # Size Variants
            variants = []

            # Select the fieldset that holds size options
            size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
            if size_fieldset:
                # Find all size input labels
                size_labels = size_fieldset.find_all('label', class_='product-form__label')
                for label in size_labels:
                    size_text = label.find('span', class_='text')
                    if size_text:
                        size_value = size_text.get_text(strip=True)

                        # Check availability by label class
                        label_class = label.get('class', [])
                        if 'available' in label_class:
                            availability = "Available"
                        elif 'soldout' in label_class:
                            availability = "Unavailable"
                        else:
                            availability = "Unknown"

                        variants.append({
                            "size": size_value,
                            "availability": availability
                        })

            # Save the variants in product_data
            product_data['variants'] = variants or None

        


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

                # Find all containers with the class 'card-product__wrapper'
                wrappers = soup.select('.card-product__wrapper')

                if not wrappers:
                    self.log_info(f"No product wrappers found on page {page_number}. Stopping.")
                    break

                initial_count = len(all_product_links)

                for wrapper in wrappers:
                    # Skip hidden wrappers (display:none or similar)
                    if 'style' in wrapper.attrs and 'display:none' in wrapper.attrs['style'].replace(" ", "").lower():
                        self.log_info("Skipping hidden wrapper.")
                        continue

                    # Only process wrappers that contain an element with the class 'media-loading'
                    if not wrapper.select_one('.media-loading'):
                        self.log_info("Skipping wrapper without media-loading.")
                        continue

                    # Within each wrapper, look for the <a> tag with class 'card-link' and href starting with '/products/'
                    link_tag = wrapper.select_one('a.card-link[href^="/products/"]')
                    if link_tag:
                        href = link_tag['href']
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        if product_url not in all_product_links:
                            self.log_info(f"Found product link: {product_url}")
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
