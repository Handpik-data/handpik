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
    def __init__(self, proxies=None, request_delay=0.1):
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
                'store_name':'Khaddi',
                'sku': None,
                'original_price': None,
                'brand':None,
                'category':None,
                'availability':None,
                'sale_price': None,
                'currency': None,
                'images': [],
                'attributes': {},
                'description': {},
                'product_link': product_link,
                'variants': [], 
            }

            product_container = soup.find('div', {'class': 'product-detail'})
            if not product_container:
                return {'error': 'Product container not found', 'product_link': product_link}

            title_tag = soup.select_one('h1.product-name, h2.product-name')
            if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            
                         # Extract brand
            brand_tag = soup.find('div', class_='product-brand')
            brand_text = brand_tag.get_text(strip=True) if brand_tag else ""

            product_data['brand'] = brand_text

            # Select all <a> tags within the breadcrumb
            a_tags = soup.select('ol.breadcrumb.asset-breadcrumb li.breadcrumb-item a')

            # Get the second <a>'s <span> text and assign to category
            if len(a_tags) >= 2:
                second_span = a_tags[1].find('span')
                if second_span:
                    product_data['category'] = second_span.get_text(strip=True)
                else:
                    print("No <span> found inside the second <a> tag.")
            else:
                print("Less than two <a> tags found in breadcrumb.")


            # SKU
            sku_tag = soup.find('div', {'class': 'product-number'})
            if sku_tag and sku_tag.find('span'):
                product_data['sku'] = sku_tag.find('span').text.strip()


              # === PRICE EXTRACTION (based on your provided logic) ===
            original_price_tag = soup.find('span', class_='strike-through list')
            sale_price_tag = soup.find('span', class_='sales reduced-price d-inline-block')

            if original_price_tag:
                price_span = original_price_tag.find('span', class_='value cc-price')
                if price_span:
                    product_data['original_price'] = re.sub(r'[^\d.]', '', price_span.get_text(strip=True))

            if sale_price_tag:
                price_span = sale_price_tag.find('span', class_='value cc-price')
                if price_span:
                    product_data['sale_price'] = re.sub(r'[^\d.]', '', price_span.get_text(strip=True))

            # Currency detection from available price strings
            price_sample = (price_span.get_text(strip=True) if price_span else '')
            match = re.search(r'(PKR|Rs|₹|\$|€|£)', price_sample)
            product_data['currency'] = match.group(1) if match else "PKR"  # Default to PKR if nothing found

            # Images
            image_elements = soup.select('.pdp-image-carousel .item img')
            for img in image_elements:
                src = img.get('src') or img.get('data-src')
                if src and src not in product_data['images']:
                    product_data['images'].append(urljoin(self.base_url, src))

            # === DETAILS DIRECTLY INTO ATTRIBUTES ===
            current_section = None

            spec_list = soup.select_one('ul.spec-list')
            if spec_list:
                for li in spec_list.find_all('li', recursive=False):
                    # Section titles like "Kurta", "Pants"
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

            # Variants / Sizes
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
                            'available': not is_disabled
                        })

            product_data['variants'] = variants

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}
        
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
                response = requests.get(paginated_url, headers=self.headers, timeout=10)
                response.raise_for_status()

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
