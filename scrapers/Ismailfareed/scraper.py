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
from utils.LoggerConstants import ISMAILFAREED_LOGGER
from urllib.parse import urljoin
import time


class ismailfareedscaper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://www.ismailfarid.com/",
            logger_name=ISMAILFAREED_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "ismailfareed"
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
            response = requests.get(product_link, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
                'product_name': None,
                'store_name': 'Ismail fareed',
                'category':None,
                'brand':None,
                'sku': None,
                'original_price': None,
                'sale_price':None,
                'currency':None,
                'availability':None,
                'images': [],
                'attributes': {},
                'description': None,
                'product_description': None,
                'product_link': product_link,
                'variants': [],
                'raw_data':{
                    'shipment_info': [],
                },
            }

            # Product Name
            title_tag = soup.select_one('h1.productView-title a')
            if title_tag:
                product_data['product_name'] = title_tag.get_text(strip=True)

            # SKU
            sku_element = soup.select_one('div.productView-info-item[data-sku] span.productView-info-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

                    # Price
            price_span = soup.select_one('span.price-item--regular span.money')
            if price_span:
                full_price_text = price_span.get_text(strip=True)
                product_data['original_price'] = full_price_text

                # Extract currency using regex (captures non-digit prefix, e.g., Rs., $, £)
                import re
                match = re.match(r'^([^\d]+)', full_price_text)
                if match:
                    product_data['currency'] = match.group(1).strip()
                else:
                    product_data['currency'] = None


                        # Extract breadcrumbs and save to attributes
            breadcrumb_nav = soup.find('nav', class_='breadcrumb')
            if breadcrumb_nav:
                crumbs = breadcrumb_nav.find_all(['a', 'span'])
                breadcrumb_texts = [crumb.get_text(strip=True) for crumb in crumbs if crumb.get_text(strip=True)]
                product_data.setdefault('attributes', {})['breadcrumbs'] = breadcrumb_texts


            # Images
            image_elements = soup.find_all('img', src=True)
            for img in image_elements:
                src = img.get('src')
                if 'cdn/shop/' in src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    else:
                        src = urljoin(self.base_url, src)
                    if src not in product_data['images']:
                        product_data['images'].append(src)

            # Short Description
            desc_div = soup.select_one('div.productView-info-item.desc')
            if desc_div:
                description = desc_div.get_text(' ', strip=True).replace('\xa0', ' ').replace('  ', ' ')
                product_data['description'] = description


                        # Extract category from span tag
    # Extract category from breadcrumb nav
            breadcrumb_nav = soup.find('nav', class_='breadcrumb breadcrumb-left')
            if breadcrumb_nav:
                breadcrumb_span = breadcrumb_nav.find_all('span')
                if breadcrumb_span:
                    # Usually, the last <span> contains the actual category/title
                    last_span_text = breadcrumb_span[-2].get_text(strip=True)  # -2 to skip the SVG span
                    product_data['category'] = last_span_text


           

                            # Initialize raw_data with shipment_info only
                product_data["raw_data"] = {
                    "shipment_info": []
                }

                # Extract delivery info
                delivery_div = soup.find('div', class_='product__text des')
                if delivery_div:
                    spans = delivery_div.select('span.delivery-info, span.delivery-icon')
                    for span in spans:
                        text = span.get_text(strip=True)
                        if text:
                            product_data['raw_data']['shipment_info'].append(text)

                # Extract shipment info
                shipment_div = soup.find('div', class_='halo-text-format')
                if shipment_div:
                    paragraphs = shipment_div.find_all('p')
                    for p in paragraphs:
                        text = p.get_text(strip=True)
                        if text:
                            product_data['raw_data']['shipment_info'].append(text)



                    # Extract Sizes and Availability
            fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
            if fieldset:
                inputs = fieldset.find_all('input', {'class': 'product-form__radio'})
                for input_tag in inputs:
                    size = input_tag.get('value')
                    input_id = input_tag.get('id')
                    label = fieldset.find('label', {'for': input_id})
                    status = True if label and 'available' in label.get('class', []) else False

                    product_data['variants'].append({
                        'size': size,
                        'status': status
                    })

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

                product_links = soup.select(
                    'a.card-media.card-media--adapt.media--hover-effect.media--loading-effect[href^="/products/"]'
                )

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                new_links_found = False
                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)
                            new_links_found = True

                if not new_links_found:
                    break  # Stop if no new links were added

                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        self.log_info(f"Collected {len(all_product_links)} product links.")
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