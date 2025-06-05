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
from utils.LoggerConstants import ETHINIC_LOGGER
from urllib.parse import urljoin
import time


class EthinicScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://pk.ethnc.com/",
            logger_name=ETHINIC_LOGGER
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
                'attributes': {
                    'color': None  # Added for color info
                },
                'description': {},
                'product_short_description': None,
                'product_description': None,
                'breadcrumbs': [],
                'product_link': product_link,
                'variants': [],
                'sizes': [],
                'stock': None,
                'shipping_handling': None,
                'care_instructions': [],
                'shipping_and_returns': None   # <- Add this
            }

            # Product Name
            title_tag = soup.select_one('h1.title')
            if title_tag:
                product_data['product_name'] = title_tag.get_text(strip=True)

            # Product Title / Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # Prices
            price_div = soup.find('div', class_='new-price')
            if price_div:
                off_price_div = price_div.find('div', class_='off-price')
                if off_price_div:
                    original_price_span = off_price_div.find('span', class_='money')
                    if original_price_span:
                        product_data['original_price'] = original_price_span.get_text(strip=True)

                sale_price_div = price_div.find('div', class_='sale-price')
                if sale_price_div:
                    percent_span = sale_price_div.find('span', class_='percentage__sale')
                    if percent_span:
                        product_data['save_percent'] = percent_span.get_text(strip=True)

                    sale_price_spans = sale_price_div.find_all('span', class_='money')
                    if sale_price_spans:
                        product_data['sale_price'] = sale_price_spans[-1].get_text(strip=True)
                else:
                    # If no off-price or sale-price divs, check for simple price div.price
                    price_simple_div = price_div.find('div', class_='price')
                    if price_simple_div:
                        price_span = price_simple_div.find('span', class_='money')
                        if price_span:
                            product_data['original_price'] = price_span.get_text(strip=True)

            # Color and SKU from style-id section
            style_id_div = soup.select_one('div.new-product-style-id.mobile-hide')
            if style_id_div:
                color_text = ''.join([t for t in style_id_div.contents if isinstance(t, str)]).strip().replace('|', '').strip()
                sku_span = style_id_div.find('span')
                if color_text:
                    product_data['attributes']['color'] = color_text
                if sku_span:
                    product_data['sku'] = sku_span.get_text(strip=True)

            # Images - outside color/sku block so it runs regardless
            slider_div = soup.find('div', class_='swiper thumbswiper')
            if slider_div:
                image_elements = slider_div.select('img')
            else:
                image_elements = []

            for img in image_elements:
                src = img.get('src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    full_url = urljoin(self.base_url, src)
                    if full_url not in product_data['images']:
                        product_data['images'].append(full_url)

            # Stock
            stock_element = soup.select_one('p.t4s-inventory_message')
            if stock_element:
                stock_count = stock_element.select_one('span.t4s-count')
                if stock_count:
                    stock_text = stock_count.get_text(strip=True)
                    if stock_text.isdigit():
                        product_data['stock'] = int(stock_text)

            # Care Instructions
            care_instructions = []

            instruction_section = soup.find('div', class_='new-instruction-inner')
            if instruction_section:
                # Composition
                composition_div = instruction_section.find('div', class_='new-composition-des')
                if composition_div:
                    metafield_div = composition_div.find('div', class_='metafield-rich_text_field')
                    if metafield_div:
                        p_tag = metafield_div.find('p')
                        if p_tag:
                            composition = p_tag.get_text(strip=True)
                            care_instructions.append("Composition: " + composition)

                # Care instructions list
                care_section = instruction_section.find('div', class_='new-composition-list')
                if care_section:
                    care_items = care_section.find_all('div', class_='new-composition-single')
                    for item in care_items:
                        text_div = item.find('div', class_='text')
                        if text_div:
                            care_text = text_div.get_text(strip=True)
                            care_instructions.append("Care: " + care_text)

            product_data['care_instructions'] = care_instructions

            # Shipping and Returns
            drawer_div = soup.select_one('div#scDraw')
            if drawer_div:
                shipping_returns_div = drawer_div.select_one('div.draw-content')
                if shipping_returns_div:
                    paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in shipping_returns_div.find_all('p')]
                    shipping_returns_text = '\n\n'.join(paragraphs)
                    product_data['shipping_and_returns'] = shipping_returns_text
                else:
                    product_data['shipping_and_returns'] = None
            else:
                product_data['shipping_and_returns'] = None

            # Short Description
            short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
            if short_desc_div:
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                product_data['product_short_description'] = ' '.join(paragraphs)

            # Product Description
            description_div = soup.select_one('div.draw-content')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                product_data['product_description'] = '\n\n'.join(paragraphs)

            # Sizes
            size_inputs = soup.find_all('input', {'name': 'SIZE', 'type': 'radio'})
            sizes = list({size_input['value'] for size_input in size_inputs})
            product_data['sizes'] = sorted(sizes)

            # Breadcrumbs
            breadcrumb_items = soup.select('nav.t4s-pr-breadcrumb a, nav.t4s-pr-breadcrumb span')
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

                # Find all product <li> tags with class containing 'product__item'
                product_items = soup.select('li.product__item')

                if not product_items:
                    self.log_info(f"No product items found on page {page_number}. Stopping.")
                    break

                initial_count = len(all_product_links)

                for item in product_items:
                    # Find the first <a> tag inside this <li> with href starting with /products/
                    link_tag = item.find('a', href=True)
                    if link_tag and link_tag['href'].startswith('/products/'):
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
