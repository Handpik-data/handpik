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
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.hushpuppies.com.pk/",
            logger_name=HUSHPUPPIES_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "hushpuppies"
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
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # Product Name
            try:
                title_div = soup.select_one('div.product-info__block-item[data-block-id="title"] h1.product-title')
                if title_div:
                    product_data['title'] = title_div.get_text(strip=True)
                else:
                    product_data['title'] = None
            except Exception as e:
                product_data['title'] = None

            # SKU
            try:
                sku_element = soup.select_one('div.product-info__block-item[data-block-type="sku"] variant-sku.variant-sku')
                if sku_element:
                    sku_text = sku_element.get_text(strip=True)
                    product_data['sku'] = sku_text.replace("SKU: ", "")
                else:
                    product_data['sku'] = None
            except Exception as e:
                product_data['sku'] = None

            # Extract all product gallery images
            try:
                buttons = soup.find_all('button', class_='product-gallery__thumbnail')
                images = []
                for button in buttons:
                    img = button.find('img')
                    if img and img.get('src'):
                        images.append(img['src'])

                product_data['images'] = images
            except Exception as e:
                product_data['images'] = []

            # Prices
            try:
                price_list = soup.find('price-list', class_='price-list--product')
                if price_list:
                    sale_price_tag = price_list.find('sale-price')
                    compare_price_tag = price_list.find('compare-at-price')

                    sale_text = sale_price_tag.get_text(strip=True) if sale_price_tag else None
                    compare_text = compare_price_tag.get_text(strip=True) if compare_price_tag else None

                    def extract_price(price_str):
                        if not price_str:
                            return None
                        price_str = re.sub(r'(Rs|₹|\$|€|£)\.?\s*', '', price_str)
                        return re.sub(r'[^\d.,]', '', price_str)

                    sale_price = extract_price(sale_text)
                    original_price = extract_price(compare_text)

                    price_text_for_currency = compare_text or sale_text
                    if price_text_for_currency:
                        match = re.search(r'(Rs|₹|\$|€|£)', price_text_for_currency)
                        currency = match.group(1) if match else None
                    else:
                        currency = None

                    if sale_price and original_price:
                        product_data['original_price'] = original_price
                        product_data['sale_price'] = sale_price
                        product_data['currency'] = currency
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None
            except Exception as e:
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None
                print(f"Error extracting price data: {e}")

            # 1–4. Extract color options, size options, and construct variants
            try:
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

                colors = [c for c in colors if c['name']]

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

                variants = []
                for color in colors:
                    for size in sizes:
                        variants.append({
                            "color": color['name'],
                            "size": size['name'],
                            "availability": "true" if size['available'] else "false"
                        })

                product_data['variants'] = variants
            except Exception as e:
                product_data['variants'] = []

            # Extract breadcrumbs
            try:
                breadcrumb_items = soup.select("nav.breadcrumb_product ol.breadcrumb__list li.breadcrumb__list-item a")
                breadcrumbs = [
                    a.get_text(strip=True)
                    for a in breadcrumb_items
                    if "javascript:history.back()" not in a.get("href", "")
                ]

                product_data['attributes'] = {
                    'breadcrumbs': breadcrumbs
                }
            except Exception as e:
                product_data['attributes'] = {
                    'breadcrumbs': []
                }

            # --- Extract product features and shipment info ---
            try:
                features = soup.select('.product-info__block-item .feature-badge p')

                product_data['raw_data'] = {
                    'installments': None,
                    'secure_payment': None,
                    'free_delivery': None,
                    'shipment_info': None
                }

                for feature in features:
                    text = feature.get_text(strip=True)
                    if "installment" in text.lower():
                        product_data['raw_data']['installments'] = text
                    elif "secure" in text.lower():
                        product_data['raw_data']['secure_payment'] = text
                    elif "delivery" in text.lower():
                        product_data['raw_data']['free_delivery'] = text

                shipment_info = []

                drawer_div = soup.select_one('div#scDraw')
                if drawer_div:
                    shipping_returns_div = drawer_div.select_one('div.draw-content')
                    if shipping_returns_div:
                        paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in shipping_returns_div.find_all('p')]
                        shipment_info.extend(paragraphs)

                accordion_divs = soup.select('accordion-disclosure div.accordion__content.prose')
                for div in accordion_divs:
                    for br in div.find_all('br'):
                        br.replace_with('\n')
                    paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in div.find_all('p')]
                    for paragraph in paragraphs:
                        if 'shipping' in paragraph.lower() or 'delivery' in paragraph.lower() or 'return' in paragraph.lower():
                            shipment_info.append(paragraph)

                product_data['raw_data']['shipment_info'] = shipment_info if shipment_info else None
            except Exception as e:
                product_data['raw_data'] = {
                    'installments': None,
                    'secure_payment': None,
                    'free_delivery': None,
                    'shipment_info': None
                }

            # --- Product Description from <details> with 'Description' summary ---
            try:
                description = None

                accordion_details = soup.select('details.accordion__disclosure')
                for detail in accordion_details:
                    summary = detail.select_one('summary')
                    if summary and 'description' in summary.get_text(strip=True).lower():
                        content_div = detail.select_one('div.accordion__content.prose')
                        if content_div:
                            paragraphs = []

                            if content_div.find('p'):
                                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in content_div.find_all('p')]
                            elif content_div.find('span'):
                                paragraphs = [span.get_text(strip=True).replace('\xa0', ' ') for span in content_div.find_all('span')]
                            elif content_div.find('div'):
                                paragraphs = [div.get_text(strip=True).replace('\xa0', ' ') for div in content_div.find_all('div')]
                            else:
                                paragraphs = [content_div.get_text(strip=True).replace('\xa0', ' ')]

                            description = '\n\n'.join(paragraphs)
                            break

                if description:
                    product_data['description'] = description
            except Exception as e:
                product_data['description'] = None

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data


    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(current_url)

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
                saved_path = await self.save_data(final_data)  
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")
