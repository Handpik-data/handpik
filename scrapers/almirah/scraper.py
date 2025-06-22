import os
import re
import json
import asyncio
import re
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import almirah_logger
from urllib.parse import urljoin
import time


class almirahscraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://almirah.com.pk/",
            logger_name=almirah_logger,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "almirah"
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
                    'reviews': 0,
                    'number_of_questions': 0,
                    'star_rating': None
                }
            }

            try:
                response = await self.async_make_request(product_link)
                soup = BeautifulSoup(response.text, "html.parser")

                try:
                    # Product Name
                    title_div = soup.select_one('div.product__title')
                    product_name = None
                    if title_div:
                        h1_tag = title_div.find('h1')
                        if h1_tag:
                            product_name = h1_tag.get_text(strip=True)
                        else:
                            h2_tag = title_div.select_one('a.product__title h2.h1')
                            if h2_tag:
                                product_name = h2_tag.get_text(strip=True)

                    if product_name:
                        product_data['title'] = product_name
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product name: {e}")
                    product_data['title'] = None

                try:
                    # SKU
                    sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
                    if sku_element:
                        product_data['sku'] = sku_element.get_text(strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping SKU: {e}")
                    product_data['sku'] = None

                try:
                    original_price_tag = soup.select_one("s.price-item--regular .money")
                    sale_price_tag = soup.select_one(".price-item--sale .money")

                    original_price_str = original_price_tag.text.strip() if original_price_tag else None
                    sale_price_str = sale_price_tag.text.strip() if sale_price_tag else None

                        # Clean numeric values (remove currency symbol, commas, etc.)
                    def parse_price(price_str):
                        if not price_str:
                            return None
                        # Extract digits and commas, remove commas, and convert to float
                        cleaned = re.sub(r'[^\d,]', '', price_str)
                        numeric_str = cleaned.replace(',', '')
                        return float(numeric_str)


                    product_data['original_price'] = parse_price(original_price_str)
                    product_data['sale_price'] = parse_price(sale_price_str)

                    # Extract currency from price string (assumes symbol is at the start)
                    sample_price = original_price_str or sale_price_str
                    if sample_price:
                        match = re.match(r'^(\D+)', sample_price)
                        currency_symbol = match.group(1).strip() if match else None
                        product_data['currency'] = currency_symbol
                    else:
                        product_data['currency'] = None

                    # Optional: log discount percent if applicable
                    original_price = product_data['original_price']
                    sale_price = product_data['sale_price']

                    if original_price is not None and sale_price is not None and sale_price < original_price:
                        save_percent = ((original_price - sale_price) / original_price) * 100
                        self.log_info(f"Save Percent: {save_percent:.0f}% off")
                    else:
                        # If there's no discount, set sale_price to None (only original price shown)
                        if sale_price is None or sale_price >= original_price:
                            product_data['sale_price'] = None

                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping prices and parsing them: {e}")
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None


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
                    self.log_debug(f"Exception occurred while scraping additional info attributes: {e}")
                    product_data['attributes'] = {}

                try:
                    # Extract high-quality product images (width=1920) based on <img class="full-image">
                    image_tags = soup.find_all('img', class_='full-image')
                    for img in image_tags:
                        src = img.get('src')
                        if src and 'width=1920' in src:
                            if src.startswith('//'):
                                src = 'https:' + src
                            full_url = urljoin(self.base_url, src)
                            if full_url not in product_data['images']:
                                product_data['images'].append(full_url)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping high-quality images: {e}")

                try:
                    # Reviews
                    review_div = soup.find('div', class_='jdgm-prev-badge')
                    if review_div:
                        avg_rating = review_div.get('data-average-rating', '0')
                        product_data['raw_data']['star_rating'] = float(avg_rating) if avg_rating else None

                        num_reviews = review_div.get('data-number-of-reviews', '0')
                        product_data['raw_data']['reviews'] = int(num_reviews) if num_reviews.isdigit() else 0

                        num_questions = review_div.get('data-number-of-questions', '0')
                        product_data['raw_data']['number_of_questions'] = int(num_questions) if num_questions.isdigit() else 0
                    else:
                        product_data['raw_data']['star_rating'] = None
                        product_data['raw_data']['reviews'] = 0
                        product_data['raw_data']['number_of_questions'] = 0
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping reviews: {e}")
                    product_data['raw_data']['star_rating'] = None
                    product_data['raw_data']['reviews'] = 0
                    product_data['raw_data']['number_of_questions'] = 0

                try:
                    # Short Description
                    short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
                    if short_desc_div:
                        paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                        product_data['attributes'] = ' '.join(paragraphs)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping short description: {e}")
                    product_data['attributes'] = ""

                try:
                    # Description
                    description_div = soup.select_one('div.accordion__content.rte')
                    if description_div:
                        for br in description_div.find_all('br'):
                            br.replace_with('\n')
                        paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                        product_data['description'] = '\n\n'.join(paragraphs)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product description: {e}")
                    product_data['description'] = ""

                try:
                    # Variants
                    variants = []
                    color = None
                    info_section = soup.select_one('div.accordion__content.additional-info.rte')
                    if info_section:
                        rows = info_section.select('tr')
                        for row in rows:
                            cells = row.find_all('td')
                            if len(cells) >= 2 and cells[0].text.strip().lower() == 'color':
                                color = cells[1].get_text(strip=True)
                                break

                    size_fieldset = soup.select_one('fieldset.product-form__input--pill.size')
                    if size_fieldset and color:
                        size_inputs = size_fieldset.find_all('input', {'type': 'radio'})
                        for input_tag in size_inputs:
                            size_value = input_tag.get('value')
                            if size_value:
                                is_disabled = 'disabled' in input_tag.attrs or 'disabled' in input_tag.get('class', [])
                                availability = not is_disabled  # True if not disabled, else False
                                variants.append({
                                    "color": color,
                                    "size": size_value,
                                    "availability": availability
                                })

                    product_data['variants'] = variants or None
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping variants: {e}")
                    product_data['variants'] = None

            except Exception as e:
                self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
               

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

                        # Look for <a class="custom-product-link-wrap" href="/products/...">
                        product_links = soup.select('a.custom-product-link-wrap[href^="/products/"]')

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