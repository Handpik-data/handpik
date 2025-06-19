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
from utils.LoggerConstants import HUSHPUPPIES_LOGGER
from urllib.parse import urljoin
import time


class HushpuppiesScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://www.hushpuppies.com.pk/",
            logger_name=HUSHPUPPIES_LOGGER
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
        'original price': None,
        'sale_price': None,
        'currency':None,
        'images': [],
        'attributes': {},
        'description': None,
        'product_link': product_link,
        'variants': [],
     
    }

            # Product Name
            title_div = soup.select_one('div.product-info__block-item[data-block-id="title"] h1.product-title')
            if title_div:
                product_data['title'] = title_div.get_text(strip=True)


            # SKU
            sku_element = soup.select_one('div.product-info__block-item[data-block-type="sku"] variant-sku.variant-sku')
            if sku_element:
                sku_text = sku_element.get_text(strip=True)
                product_data['sku'] = sku_text.replace("SKU: ", "")
         
         
               # Extract all product gallery images
            buttons = soup.find_all('button', class_='product-gallery__thumbnail')
            images = []
            for button in buttons:
                img = button.find('img')
                if img and img.get('src'):
                    images.append(img['src'])

            product_data['images'] = images

            

                    # Prices
            price_list = soup.find('price-list', class_='price-list--product')
            if price_list:
                sale_price_tag = price_list.find('sale-price')
                compare_price_tag = price_list.find('compare-at-price')

                sale_text = sale_price_tag.get_text(strip=True) if sale_price_tag else None
                compare_text = compare_price_tag.get_text(strip=True) if compare_price_tag else None

                # Decide final original/sale prices
                product_data['original price'] = compare_text or sale_text
                product_data['sale price'] = sale_text if compare_text else None

                # Extract currency directly from the price string (e.g., "Rs.5,499.00" → "Rs")
                price_text_for_currency = compare_text or sale_text
                if price_text_for_currency:
                    match = re.search(r'(Rs|₹|\$|€|£)', price_text_for_currency)
                    product_data['currency'] = match.group(1) if match else None
                else:
                    product_data['currency'] = None                     # Find the fieldset for the color option
           
                        # 1. Extract color options
                colors = []
                color_inputs = soup.select('div.variant-picker__option-values input[type="radio"]')
                for input_tag in color_inputs:
                    label = input_tag.find_next_sibling('label')
                    if label:
                        color_name_tag = label.select_one('span.sr-only')
                        if color_name_tag:
                            colors.append({
                                "id": input_tag.get('value'),
                                "name": color_name_tag.text.strip()
                            })

                # Avoid blank color names
                colors = [c for c in colors if c['name']]

                # 2. Extract size options and availability
                sizes = []
                size_container = soup.select_one('fieldset.variant-picker__option:has(legend:-soup-contains("Size"))')
                if size_container:
                    size_inputs = size_container.find_all('input', {'type': 'radio'})
                    for input_tag in size_inputs:
                        label = size_container.find('label', {'for': input_tag.get('id')})
                        if label:
                            size_text = label.get_text(strip=True)
                            is_unavailable = 'is-disabled' in label.get('class', [])
                            sizes.append({
                                "name": size_text,
                                "available": not is_unavailable
                            })

                # 3. Construct variants list (only once per color-size pair)
                variants = []
                for color in colors:
                    for size in sizes:
                        variants.append({
                            "color": color['name'],
                            "size": size['name'],
                            "availability": "Available" if size['available'] else "Sold Out"
                        })

                # 4. Save in product_data
                product_data['variants'] = variants


           

            

            # Short Description
            short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
            if short_desc_div:
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                product_data['product_short_description'] = ' '.join(paragraphs)

            # Product Description from accordion-disclosure
            accordion_desc = soup.select_one('accordion-disclosure div.accordion__content.prose')
            if accordion_desc:
                # Replace <br> with new lines if any
                for br in accordion_desc.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in accordion_desc.find_all('p')]
                product_data['description'] = '\n\n'.join(paragraphs)
            else:
                # fallback to your old selector if needed
                description_div = soup.select_one('div.draw-content')
                if description_div:
                    for br in description_div.find_all('br'):
                        br.replace_with('\n')
                    paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                    product_data['description'] = '\n\n'.join(paragraphs)


                accordion_divs = soup.select('div.accordion__content.prose')
                print(f"Found {len(accordion_divs)} accordion div(s)")

         

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

                    # Find all <a> tags with class 'product-card__media'
                    product_links = soup.select('a.product-card__media[href^="/products/"]')

                    if not product_links:
                        self.log_info(f"No product links found on page {page_number}. Stopping.")
                        break

                    initial_count = len(all_product_links)

                    for tag in product_links:
                        href = tag.get('href')
                        if href:
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
