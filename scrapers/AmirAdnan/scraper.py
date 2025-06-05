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
from utils.LoggerConstants import AMIR_ADNAN
from urllib.parse import urljoin
from urllib.parse import urlsplit, urlunsplit, urljoin

import time


class AmirAdnan_Scrapper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://amiradnan.com/",
            logger_name=AMIR_ADNAN
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
                'product_name': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'images': [],
                'product_description': None,
                'product_link': product_link,
                'sku': None,
                'all_sizes': None,
                'delivery_info': None,
                'shipping_charges': None,
                'taxes_and_duties': None,
            }

            # Product Name
            h1_tag = soup.select_one('h1.product-title span')
            if h1_tag:
                product_data['product_name'] = h1_tag.get_text(strip=True)

            # SKU
            sku_element = soup.select_one('div.sku-product span')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # Description
            description_div = soup.select_one('div.short-description')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [
                    tag.get_text(separator='\n', strip=True).replace('\xa0', ' ')
                    for tag in description_div.find_all(['p', 'span'])
                ]
                product_data['product_description'] = '\n'.join(paragraphs)

            # Shipping Charges
            shipping_div = soup.select_one('div#collapse-tab2')
            if shipping_div:
                shipping_texts = [h5.get_text(strip=True) for h5 in shipping_div.find_all('h5')]
                product_data['shipping_charges'] = '\n'.join(shipping_texts)

            # Delivery Information
            delivery_div = soup.select_one('div#collapse-tab3')
            if delivery_div:
                delivery_texts = [h5.get_text(strip=True) for h5 in delivery_div.find_all('h5')]
                product_data['delivery_info'] = '\n'.join(delivery_texts)

            # Taxes & Duties
            taxes_div = soup.select_one('div#collapse-tab4')
            if taxes_div:
                taxes_texts = [h5.get_text(strip=True) for h5 in taxes_div.find_all('h5')]
                product_data['taxes_and_duties'] = '\n'.join(taxes_texts)

            # Sizes
            swatch_container = soup.select_one('div.swatch[data-option-index="0"]')
            if swatch_container:
                size_divs = swatch_container.select('div.swatch-element')
                all_sizes = [size_div.get('data-value') for size_div in size_divs if size_div.get('data-value')]
                product_data['all_sizes'] = all_sizes if all_sizes else None

            # Prices
            prices_div = soup.find('div', class_='prices')
            if prices_div:
                sale_price_tag = prices_div.select_one('span.price.on-sale span.money')
                if sale_price_tag:
                    product_data['sale_price'] = sale_price_tag.get_text(strip=True)

                original_price_tag = prices_div.select_one('span.compare-price span.money')
                if original_price_tag:
                    product_data['original_price'] = original_price_tag.get_text(strip=True)

            # Sale Percent
            label_div = soup.find('div', class_='product-label')
            if label_div:
                sale_label = label_div.find('strong', class_='sale-label')
                if sale_label:
                    product_data['save_percent'] = sale_label.get_text(strip=True)

            # Images extraction
            image_links = []
            media_divs = soup.select('div.product-single__media a[data-image]')
            for a_tag in media_divs:
                img_url = a_tag.get('data-zoom-image') or a_tag.get('data-image')
                if img_url:
                    if img_url.startswith('//'):
                        img_url = 'https:' + img_url
                    image_links.append(img_url)
            product_data['images'] = image_links

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

                    product_anchors = soup.select('a[href^="/collections/"][href*="/products/"]')

                    if not product_anchors:
                        self.log_info(f"No product links found on page {page_number}. Stopping.")
                        break

                    for anchor in product_anchors:
                        product_url = urljoin(self.base_url, anchor['href'])
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
