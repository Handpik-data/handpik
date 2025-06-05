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
    def __init__(self):
        super().__init__(
            base_url="https://generation.com.pk/",
            logger_name=GENERATION_LOGGER
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[509, 510, 511, 512],
            allowed_methods=frozenset(['GET', 'POST'])
        )
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
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
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(product_link) as response:
                    if response.status != 200:
                        self.log_error(f"Failed to get product page: {product_link} Status: {response.status}")
                        return {'error': 'Failed to fetch product page', 'product_link': product_link}
                    html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            product_data = {
            'product_name': None,
            'original_price': None,
            'sale_price': None,
            'images': [],
            'product_description': None,
            'care_instructions': None,  
            'product_link': product_link,
            'available_sizes': [],      # Stores available sizes
            'unavailable_sizes': [],    # Stores unavailable sizes
            'available_colors': [],     # Stores available colors
            'unavailable_colors': [],   # Stores unavailable colors
        }


             # Product Name
            product_name = None

            # Select the <h1> with class "ProductMeta__Title"
            h1_tag = soup.select_one('h1.ProductMeta__Title')

            if h1_tag:
                product_name = h1_tag.get_text(strip=True)

            if product_name:
                product_data['product_name'] = product_name

            # SKU
            sku_element = soup.select_one('span.variant-sku')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)
            price_wrapper = soup.find('div', class_='ProductMeta__PriceList')
            if price_wrapper:
                # Try to find sale price first
                sale_price_tag = price_wrapper.find('span', class_='Price--highlight')
                original_price_tag = price_wrapper.find('span', class_='Price--compareAt')
                
                if sale_price_tag and original_price_tag:
                    # Both sale and original present
                    sale_price_str = sale_price_tag.get_text(strip=True)
                    original_price_str = original_price_tag.get_text(strip=True)
                    product_data['sale_price'] = sale_price_str
                    product_data['original_price'] = original_price_str
                elif sale_price_tag and not original_price_tag:
                    # Sale price but no original price (rare but possible)
                    sale_price_str = sale_price_tag.get_text(strip=True)
                    product_data['sale_price'] = sale_price_str
                    product_data['original_price'] = None
                else:
                    # No sale price, so look for a single price shown as original price or regular price
                    single_price_tag = price_wrapper.find('span', class_='Price') or price_wrapper.find('span', class_='Price--regular')
                    if single_price_tag:
                        price_str = single_price_tag.get_text(strip=True)
                        product_data['original_price'] = price_str
                        product_data['sale_price'] = None
                    else:
                        # No price found at all
                        product_data['original_price'] = None
                        product_data['sale_price'] = None
            else:
                product_data['original_price'] = None
                product_data['sale_price'] = None


            
             
            available_sizes = []
            unavailable_sizes = []

            try:
                size_buttons = soup.select('div.Popover__ValueList button.Popover__Value_size')
                for button in size_buttons:
                    size_value = button.get('data-value')
                    if size_value:
                        class_list = button.get('class', [])
                        available = 'hide_variant' not in class_list
                        if available:
                            available_sizes.append(size_value)
                        else:
                            unavailable_sizes.append(size_value)

            except Exception as e:
                self.log_error(f"Error extracting sizes: {e}")

            # Save separately in product_data
            product_data['available_sizes'] = available_sizes
            product_data['unavailable_sizes'] = unavailable_sizes



          # Extract color buttons (updated class name to match your snippet)
            color_buttons = soup.select('div.Popover__ValueList button.Popover__Value_color')

            available_colors = []
            unavailable_colors = []

            for btn in color_buttons:
                color_name = btn.get('data-value', '').strip()
                if not color_name:
                    continue  # skip if no color name
                
                classes = btn.get('class', [])
                if 'hide_variant' in classes:
                    unavailable_colors.append(color_name)
                else:
                    available_colors.append(color_name)

            # Save to product_data dict
            product_data['available_colors'] = available_colors
            product_data['unavailable_colors'] = unavailable_colors




                
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

                product_data['product_description'] = product_description_text.strip()
                product_data['care_instructions'] = care_instructions.strip()  # ✅ Moved to top level

               
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

                # Updated selector for the correct <a> tag
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
