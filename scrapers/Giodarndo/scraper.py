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
from utils.LoggerConstants import Giordando_LOGGER
from urllib.parse import urljoin, urlparse
import time


class GiordandoScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://giordanopk.com/",
            logger_name=Giordando_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Giordando"
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
                'material': None,
                'color_accuracy_notice': None
            }
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # ---------------- Product Name ----------------
            try:
                title_div = soup.find('div', class_='product__section--header product__section--element product__section--product_title')
                if title_div:
                    h1_tag = title_div.find('h1', class_='product__section-title product-title')
                    if h1_tag:
                        product_data['title'] = h1_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception while scraping product name: {e}")

            # ---------------- SKU ----------------
            try:
                sku_span = soup.select_one('div.product__section--sku span#variantSku')
                product_data['sku'] = sku_span.get_text(strip=True) if sku_span else None
            except Exception as e:
                self.log_debug(f"Exception while scraping SKU: {e}")

            # ---------------- Price ----------------
            try:
                price_group = soup.find('div', class_='price__pricing-group')

                original_price = None
                sale_price = None
                currency = None

                def extract_price(price_str):
                    match = re.match(r'([^\d]*)([\d,]+\.?\d*)', price_str.strip())
                    if match:
                        symbol, amount = match.groups()
                        amount = amount.replace(',', '')
                        return symbol.strip(), float(amount)
                    return None, None

                if price_group:
                    # Regular prices
                    regular_price_tags = price_group.find_all('span', class_='price-item price-item--regular')
                    regular_prices_raw = [tag.get_text(strip=True) for tag in regular_price_tags if tag.get_text(strip=True)]

                    # Sale price
                    sale_price_tag = price_group.find('span', class_='price-item price-item--sale')
                    sale_price_raw = sale_price_tag.get_text(strip=True) if sale_price_tag else None

                    # Parse logic
                    if sale_price_raw and regular_prices_raw:
                        _, sale = extract_price(sale_price_raw)
                        _, regular = extract_price(regular_prices_raw[-1])

                        if sale == regular:
                            currency, original_price = extract_price(sale_price_raw)
                            sale_price = None
                        else:
                            currency, sale_price = extract_price(sale_price_raw)
                            _, original_price = extract_price(regular_prices_raw[-1])
                    elif regular_prices_raw:
                        currency, original_price = extract_price(regular_prices_raw[0])

                product_data['original_price'] = original_price
                product_data['sale_price'] = sale_price
                product_data['currency'] = currency or "PKR"

            except Exception as e:
                self.log_debug(f"Exception while scraping price: {e}")

            # ---------------- Additional Attributes ----------------
            try:
                additional_info = {}
                details = soup.find('details', id=lambda x: x and x.startswith('Details-additional_information'))
                if details:
                    table = details.find('table')
                    if table:
                        for row in table.find_all('tr'):
                            cells = row.find_all('td')
                            if len(cells) == 2:
                                key = cells[0].get_text(strip=True)
                                value = cells[1].get_text(strip=True)
                                additional_info[key] = value
                product_data['attributes'] = additional_info
            except Exception as e:
                self.log_debug(f"Exception while scraping additional attributes: {e}")

            # ---------------- Images ----------------
            try:
                image_containers = soup.find_all('div', class_='product-media-container')
                for container in image_containers:
                    img_tag = container.find('img')
                    if img_tag:
                        src = img_tag.get('src')
                        if src:
                            full_url = urljoin(self.base_url, src)
                            if full_url not in product_data['images']:
                                product_data['images'].append(full_url)
            except Exception as e:
                self.log_debug(f"Exception while scraping images: {e}")

            # ---------------- Description ----------------
            try:
                description_div = soup.find('div', class_='tabbed__product-content')
                if description_div:
                    paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                    product_data['description'] = '\n\n'.join(paragraphs)
            except Exception as e:
                self.log_debug(f"Exception while scraping description: {e}")

            # ---------------- Composition ----------------
            try:
                composition_div = soup.find('div', {'id': re.compile(r'.*-tab-10')})
                if composition_div:
                    paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in composition_div.find_all('p')]
                    product_data['raw_data']['material'] = '\n\n'.join(paragraphs)
            except Exception as e:
                self.log_debug(f"Exception while scraping composition: {e}")
                product_data['raw_data']['material'] = None

            # ---------------- Color Accuracy Notice ----------------
            try:
                color_accuracy_div = soup.find('div', {'id': re.compile(r'.*-tab-12')})
                if color_accuracy_div:
                    paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in color_accuracy_div.find_all('p')]
                    product_data['raw_data']['color_accuracy_notice'] = '\n\n'.join(paragraphs)
            except Exception as e:
                self.log_debug(f"Exception while scraping notice: {e}")
                product_data['raw_data']['color_accuracy_notice'] = None

            # ---------------- Variants ----------------
            try:
                variants = []
                colors = []
                sizes = []

                colors_container = soup.find('div', {'data-option-index': '2'})
                if colors_container:
                    color_options = colors_container.find_all('div', class_='swatches__swatch--color')
                    for option in color_options:
                        input_tag = option.find('input', {'type': 'radio'})
                        if input_tag:
                            colors.append({
                                "color": input_tag.get('value'),
                                "availability": 'soldout' not in option.get('class', [])
                            })

                sizes_container = soup.find('div', {'data-option-index': '1'})
                if sizes_container:
                    size_options = sizes_container.find_all('div', class_='swatches__swatch--regular')
                    for option in size_options:
                        input_tag = option.find('input', {'type': 'radio'})
                        if input_tag:
                            sizes.append({
                                "size": input_tag.get('value'),
                                "availability": 'soldout' not in option.get('class', [])
                            })

                if colors and sizes:
                    for color in colors:
                        for size in sizes:
                            variants.append({
                                "color": color['color'],
                                "size": size['size'],
                                "availability": color['availability'] and size['availability']
                            })
                elif sizes:
                    for size in sizes:
                        variants.append({
                            "color": None,
                            "size": size['size'],
                            "availability": size['availability']
                        })
                elif colors:
                    for color in colors:
                        variants.append({
                            "color": color['color'],
                            "size": None,
                            "availability": color['availability']
                        })

                product_data['variants'] = variants or None

            except Exception as e:
                self.log_debug(f"Exception while scraping variants: {e}")

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {e}")

        return product_data
  


    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Updated selector for <a> tags with href containing '/products/'
                product_links = soup.select('a[href*="/products/"]')

                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                # Extract and add product URLs
                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        # Convert relative URL to absolute URL
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Pagination: look for next page link (adjust selector if site uses different pagination)
                next_page_link = soup.select_one('a.next')
                if next_page_link:
                    next_href = next_page_link.get('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                        continue
                    else:
                        self.log_info("Next page href not found. Stopping pagination.")
                        break
                else:
                    self.log_info("No next page link found. Finished scraping all pages.")
                    break

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
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
