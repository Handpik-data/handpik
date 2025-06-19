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
        try:
            response = requests.get(product_link)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
                'title': None,
                'availability':None,
                'brand':None,
                'category':None,
                'store_name': 'Almirah',
                'original_price': None,
                'sale_price': None,
                'currency': None,
                'images': [],
                'brand': None,
                'description': {},
                'attributes': None,
                'product_link': product_link,
                'variants': [],
                'raw_data': {
                    'reviews': 0,
                    'number_of_questions': 0,
                    'star_rating': None
                }
            }

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

            # Product Title / Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

                    # Prices
            price_wrapper = soup.find('div', class_='price--show-badge')
            if price_wrapper:
                original_price_str = sale_price_str = None

                regular_price = price_wrapper.select_one('.price__regular .money')
                if regular_price:
                    original_price_str = regular_price.get_text(strip=True)
                    original_price_clean = re.findall(r'[\d,]+', original_price_str)
                    product_data['original_price'] = original_price_clean[0] if original_price_clean else None
                else:
                    product_data['original_price'] = None

                sale_price_tag = price_wrapper.select_one('.price__sale .price-item--sale .money')
                if sale_price_tag:
                    sale_price_str = sale_price_tag.get_text(strip=True)
                    sale_price_clean = re.findall(r'[\d,]+', sale_price_str)
                    product_data['sale_price'] = sale_price_clean[0] if sale_price_clean else None
                else:
                    product_data['sale_price'] = None

                sample_price = original_price_str or sale_price_str
                if sample_price:
                    match = re.match(r'^(\D+)', sample_price)
                    currency_symbol = match.group(1).strip() if match else None
                    product_data['currency'] = currency_symbol
                else:
                    product_data['currency'] = None

                # Calculate save_percent but don't save it to product_data
                def parse_price(price_str):
                    if not price_str:
                        return None
                    cleaned = re.sub(r'[^\d.]', '', price_str)
                    parts = cleaned.split('.')
                    if len(parts) > 2:
                        cleaned = parts[0] + '.' + ''.join(parts[1:])
                    return float(cleaned)

                original_price = parse_price(original_price_str)
                sale_price = parse_price(sale_price_str)

                if original_price is not None and sale_price is not None and sale_price < original_price:
                    save_percent = ((original_price - sale_price) / original_price) * 100
                    self.log_info(f"Save Percent: {save_percent:.0f}% off")
                else:
                    if sale_price is None or sale_price >= original_price:
                        product_data['sale_price'] = None

                sample_price = original_price_str or sale_price_str
                if sample_price:
                    match = re.match(r'^(\D+)', sample_price)
                    currency_symbol = match.group(1).strip() if match else None
                    product_data['currency'] = currency_symbol
                else:
                    product_data['currency'] = None

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

            # Short Description
            short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
            if short_desc_div:
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                product_data['attributes'] = ' '.join(paragraphs)

            # Description
            description_div = soup.select_one('div.accordion__content.rte')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                product_data['description'] = '\n\n'.join(paragraphs)

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
                            "available": availability  # Boolean True or False
                        })

            product_data['variants'] = variants or None


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