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
from utils.LoggerConstants import KHADDI_LOGGER
from urllib.parse import urljoin

class KhaddiScrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://pk.khaadi.com/",
            logger_name=KHADDI_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "khaddi"
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
            'currency': 'PKR',  # Default currency for Khaadi
            'original_price': None,
            'sale_price': None,
            'images': [],
            'brand': None,
            'availability': None,
            'category': None,
            'product_url': product_link,
            'variants': [],
            'attributes': {},
            'raw_data': {}
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # --- Title ---
            try:
                product_container = soup.find('div', {'class': 'product-detail'})
                if not product_container:
                    return {'error': 'Product container not found', 'product_link': product_link}

                title_tag = soup.select_one('h1.product-name, h2.product-name')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while parsing product title: {str(e)}', 'product_link': product_link}

            # --- Brand ---
            try:
                brand_tag = soup.find('div', class_='product-brand')
                product_data['brand'] = brand_tag.get_text(strip=True) if brand_tag else ""
            except Exception as e:
                return {'error': f'Exception occurred while extracting brand: {str(e)}', 'product_link': product_link}

            # --- Category ---
            try:
                a_tags = soup.select('ol.breadcrumb.asset-breadcrumb li.breadcrumb-item a')
                if len(a_tags) >= 2:
                    second_span = a_tags[1].find('span')
                    if second_span:
                        product_data['category'] = second_span.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting category from breadcrumb: {str(e)}', 'product_link': product_link}

            # --- SKU ---
            try:
                sku_tag = soup.find('div', {'class': 'product-number'})
                if sku_tag and sku_tag.find('span'):
                    product_data['sku'] = sku_tag.find('span').text.strip()
            except Exception as e:
                return {'error': f'Exception occurred while extracting SKU: {str(e)}', 'product_link': product_link}
        
                # --- PRICES ---
            original_price = sale_price = save_percent = currency = None

            try:
                del_price = soup.find('span', style=lambda value: value and 'line-through' in value)
            except Exception as e:
                print("Error finding deleted price span:", e)
                del_price = None

            try:
                ins_price = soup.find('span', {'content': True})
            except Exception as e:
                print("Error finding inserted price span:", e)
                ins_price = None

            try:
                del_text = del_price.get_text(strip=True) if del_price else None
                ins_text = ins_price.get_text(strip=True) if ins_price else None
            except Exception as e:
                print("Error extracting price text:", e)
                del_text = ins_text = None

            # Extract currency and numeric value
            def extract_parts(price_str):
                try:
                    if not price_str:
                        return None, None
                    match = re.match(r"([A-Za-z]+)?\s?([\d,]+)", price_str)
                    if match:
                        currency = match.group(1)
                        value = float(match.group(2).replace(",", ""))
                        return currency, value
                except Exception as e:
                    print(f"Error parsing price string '{price_str}':", e)
                return None, None

            try:
                cur1, val1 = extract_parts(del_text)
                cur2, val2 = extract_parts(ins_text)

                # Set currency (prefer cur1)
                currency = cur1 or cur2

                # Assign prices based on numeric comparison
                if val1 is not None and val2 is not None:
                    if val1 > val2:
                        original_price = f"{cur1} {int(val1):,}" if cur1 else f"{int(val1):,}"
                        sale_price = f"{cur2} {int(val2):,}" if cur2 else f"{int(val2):,}"
                    else:
                        original_price = f"{cur2} {int(val2):,}" if cur2 else f"{int(val2):,}"
                        sale_price = f"{cur1} {int(val1):,}" if cur1 else f"{int(val1):,}"
                elif val2 is not None:
                    original_price = f"{cur2} {int(val2):,}" if cur2 else f"{int(val2):,}"
                elif val1 is not None:
                    original_price = f"{cur1} {int(val1):,}" if cur1 else f"{int(val1):,}"
            except Exception as e:
                print("Error comparing and assigning prices:", e)

            # Override original price if found in a sales container
            try:
                sales_container = soup.find('span', class_='sales')
                if sales_container:
                    price_span = sales_container.find('span', class_='value cc-price')
                    if price_span:
                        original_price = price_span.get_text(strip=True)
            except Exception as e:
                print("Error checking sales container override:", e)

            # Extract SAVE % badge
            try:
                badge = soup.find('span', {'class': 'sales'})
                if badge:
                    match = re.search(r"SAVE\s+(\d+)%", badge.text.strip(), re.IGNORECASE)
                    save_percent = match.group(1) if match else None
            except Exception as e:
                print("Error extracting SAVE % badge:", e)

            # Save to product_data dictionary
            product_data['currency'] = currency
            product_data['original_price'] = original_price
            product_data['sale_price'] = sale_price
            product_data['save_percent'] = save_percent

                # Continue processing other fields rather than returning early
            # --- IMAGES ---
            try:
                image_elements = soup.select('.pdp-image-carousel .item img')
                for img in image_elements:
                    src = img.get('src') or img.get('data-src')
                    if src and src not in product_data['images']:
                        product_data['images'].append(urljoin(self.base_url, src))
            except Exception as e:
                return {'error': f'Exception occurred while extracting images: {str(e)}', 'product_link': product_link}

            # --- ATTRIBUTES / SPECIFICATIONS ---
            try:
                current_section = None
                spec_list = soup.select_one('ul.spec-list')
                if spec_list:
                    for li in spec_list.find_all('li', recursive=False):
                        if 'spec-list-title' in li.get('class', []):
                            current_section = li.get_text(strip=True)
                            product_data['attributes'][current_section] = {}
                        elif current_section:
                            strong = li.find('strong')
                            if strong:
                                key = strong.text.strip().replace(':', '')
                                strong.extract()
                                value = li.get_text(strip=True)
                                product_data['attributes'][current_section][key] = value
                            else:
                                text = li.get_text(strip=True)
                                if text:
                                    product_data['attributes'][current_section][text] = None
            except Exception as e:
                return {'error': f'Exception occurred while extracting attributes/specifications: {str(e)}', 'product_link': product_link}

            # --- VARIANTS / SIZES ---
            try:
                size_items = soup.select('.size-item')
                variants = []
                for size_item in size_items:
                    input_tag = size_item.find('input', {'type': 'radio'})
                    if input_tag:
                        size = input_tag.get('data-attr-value')
                        is_disabled = input_tag.has_attr('disabled')
                        if size:
                            variants.append({
                                'size': size,
                                'availability': not is_disabled
                            })
                product_data['variants'] = variants
                # Set overall availability based on variants
                product_data['availability'] = any(v['availability'] for v in variants) if variants else None
            except Exception as e:
                return {'error': f'Exception occurred while extracting variants/sizes: {str(e)}', 'product_link': product_link}

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data

        
    async def scrape_products_links(self, url):
                all_product_links = []
                page_number = 1
                start = 0
                products_on_page = 49

                while True:
                    try:
                        paginated_url = f"{url}?start={start}&sz={products_on_page}"
                        start = products_on_page
                        products_on_page += products_on_page
                        self.log_info(f"Scraping page {page_number}: {paginated_url}")
                        response = await self.async_make_request(paginated_url)

                        soup = BeautifulSoup(response.text, 'html.parser')
                        link_tags = soup.find_all('a', class_='plp-tap-mobile plpRedirectPdp')

                        if not link_tags:
                            self.log_info(f"No products found on page {page_number}, stopping.")
                            break

                        for tag in link_tags:
                            if tag.has_attr('href'):
                                product_url = urljoin(self.base_url, tag['href'])
                                if product_url not in all_product_links:
                                    all_product_links.append(product_url)

                        page_number += 1

                    except Exception as e:
                        self.log_error(f"Error scraping page {page_number}: {e}")
                        break

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
