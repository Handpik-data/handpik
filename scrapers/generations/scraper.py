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
from utils.LoggerConstants import GENERATION_LOGGER
from urllib.parse import urljoin
import time


class GenerationScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://generation.com.pk/",
            logger_name=GENERATION_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "generations"
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
            'raw_data': {
                'care_instructions': None
            }
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                product_title_tag = soup.find('h1', class_="ProductMeta__Title Heading u-h2")
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            try:
                sku_element = soup.select_one('span.variant-sku')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product SKU: {e}")

            try:
                price_wrapper = soup.find('div', class_='ProductMeta__PriceList')
                if price_wrapper:
                    # Try to find sale price first
                    sale_price_tag = price_wrapper.find('span', class_='Price--highlight')
                    original_price_tag = price_wrapper.find('span', class_='Price--compareAt')

                    # Initialize currency
                    currency = None

                    if sale_price_tag and original_price_tag:
                        # Both sale and original prices are present
                        sale_price_str = sale_price_tag.get_text(strip=True)
                        original_price_str = original_price_tag.get_text(strip=True)
                        product_data['sale_price'] = re.sub(r'[^\d]', '', sale_price_str)
                        product_data['original_price'] = re.sub(r'[^\d]', '', original_price_str)
                    elif sale_price_tag and not original_price_tag:
                        # Sale price but no original price
                        sale_price_str = sale_price_tag.get_text(strip=True)
                        product_data['sale_price'] = re.sub(r'[^\d]', '', sale_price_str)
                        product_data['original_price'] = None
                    else:
                        # Look for a single price (regular price)
                        single_price_tag = price_wrapper.find('span', class_='Price') or price_wrapper.find('span', class_='Price--regular')
                        if single_price_tag:
                            price_str = single_price_tag.get_text(strip=True)
                            product_data['original_price'] = re.sub(r'[^\d]', '', price_str)
                            product_data['sale_price'] = None
                        else:
                            product_data['original_price'] = None
                            product_data['sale_price'] = None

                    # Extract currency
                    price_text = None
                    if sale_price_tag:
                        price_text = sale_price_tag.get_text(strip=True)
                    elif original_price_tag:
                        price_text = original_price_tag.get_text(strip=True)
                    elif 'single_price_tag' in locals() and single_price_tag:
                        price_text = single_price_tag.get_text(strip=True)

                    if price_text:
                        match = re.match(r'([^\d\s]+)', price_text)
                        if match:
                            currency = match.group(1)
                    product_data['currency'] = currency
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")

            variants = []

            try:
                # Extract color buttons
                color_buttons = soup.select('div.Popover__Content div.Popover__ValueList button.Popover__Value_color')
                colors = []
                for button in color_buttons:
                    color_value = button.get('data-value', '').strip()
                    if color_value:
                        class_list = button.get('class', [])
                        availability = 'available' if 'hide_variant' not in class_list else 'unavailable'
                        colors.append({'color': color_value, 'availability': availability})
            except Exception as e:
                self.log_error(f"Error extracting colors: {e}")

            try:
                # Extract size buttons
                size_buttons = soup.select('div.Popover__ValueList button.Popover__Value_size')
                sizes = []
                for button in size_buttons:
                    size_value = button.get('data-value', '').strip()
                    if size_value:
                        class_list = button.get('class', [])
                        availability = 'available' if 'hide_variant' not in class_list else 'unavailable'
                        sizes.append({'size': size_value, 'availability': availability})
            except Exception as e:
                self.log_debug(f"Error extracting sizes: {e}")

            # Combine each color with each size and set availability as "true"/"false" (string)
            for color in colors:
                for size in sizes:
                    combined_availability = (
                        'false'
                        if color['availability'] == 'unavailable' or size['availability'] == 'unavailable'
                        else 'true'
                    )
                    variants.append({
                        'size': size['size'],
                        'color': color['color'],
                        'availability': combined_availability
                    })

            product_data['variants'] = variants

            try:
                # Extract product images from <img> tags using data-original-src
                image_tags = soup.find_all('img', attrs={'data-original-src': True})

                product_images = []

                for img in image_tags:
                    img_url = img.get('data-original-src')
                    if img_url:
                        # Convert to full URL if it starts with //
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        product_images.append(img_url)

                # Remove duplicates, if any
                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

            try:
                # Extract description and care instructions
                description_section = soup.find('div', class_='ProductMeta__Description')

                if description_section:
                    paragraphs = description_section.find_all('p')

                    product_description_text = ""
                    care_instructions = ""

                    for p in paragraphs:
                        text = p.get_text(separator="\n", strip=True)

                        # Detect care instructions paragraph
                        if 'CARE INSTRUNCTIONS' in text.upper():
                            care_instructions = text.replace('CARE INSTRUNCTIONS', '').strip()
                        else:
                            product_description_text += text + "\n"

                    product_data['description'] = product_description_text.strip()
                    product_data['raw_data'] = {
                        'care_instructions': care_instructions.strip() if care_instructions else None
                    }
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description and care instructions: {e}")
                product_data['description'] = ""
                product_data['raw_data'] = {
                    'care_instructions': None
                }

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")
           

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

                        product_links = soup.select('a.ProductItem__ImageWrapper.desktop-img[href^="/collections/"]')

                        if not product_links:
                            self.log_info(f"No product links found on page {page_number}. Stopping.")
                            break

                        for link_tag in product_links:
                            href = link_tag.get('href')
                            if href:
                                product_url = urljoin(self.base_url, href)
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
