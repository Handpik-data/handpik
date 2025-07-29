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
from utils.LoggerConstants import LimeLight_Logger
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.parse import urljoin
import time



class LimeLightScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.limelight.pk/",
            logger_name=LimeLight_Logger,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "LimeLight"
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
                'raw_data': {}
            }

            try:
                response = await self.async_make_request(product_link)
                soup = BeautifulSoup(response.text, "html.parser")

                try:
                    title_tag = soup.select_one('div.product__title h1')
                    if not title_tag:
                        title_tag = soup.select_one('div.product__title a.product__title h2')

                    product_data['title'] = title_tag.get_text(strip=True) if title_tag else None

                except Exception as e:
                    print(f"Error extracting product title: {e}")

                try:
                    sku_element = soup.select_one('p.cstm-variant-sku span.cstm-variant-sku-code')
                    product_data['sku'] = sku_element.get_text(strip=True) if sku_element else None

                except Exception as e:
                    print(f"Error extracting SKU: {e}")

                try:
                    breadcrumb_div = soup.find('div', id='breadcrumb')
                    breadcrumb_path = []

                    if breadcrumb_div:
                        breadcrumb_links = breadcrumb_div.find_all('a')

                        for link in breadcrumb_links:
                            text = link.get_text(strip=True)
                            if text and text.lower() != 'home':
                                breadcrumb_path.append(text)

               
                    product_data['category'] = breadcrumb_path

              
               

                except Exception as e:
                    print(f"Error extracting breadcrumbs: {e}")

                try:
              
                    breadcrumb_div = soup.find('div', id='breadcrumb')
                    breadcrumb_path = []

                    if breadcrumb_div:
              
                        breadcrumb_links = breadcrumb_div.find_all('a')

                        for link in breadcrumb_links:
                            text = link.get_text(strip=True)
                      
                            if text and text.lower() != 'home':
                                breadcrumb_path.append(text)

               
                    product_data['category'] = breadcrumb_path

        

                except Exception as e:
                    print(f"Error extracting breadcrumbs: {e}")


                    # Also save the last breadcrumb as product type (optional)
                    if breadcrumb_path:
                        product_data['attributes']['product_type'] = breadcrumb_path[-1]

                except Exception as e:
                    print(f"Error extracting breadcrumbs or product type: {e}")


                try:
                    # Updated class based on your description
                    price_div = soup.find('div', class_='price price--large price--on-sale price--show-badge')

                    def extract_price(text):
                        text = text.replace("From", "").strip()
                        currency_match = re.match(r'^(\D+)', text)
                        currency = currency_match.group(1).strip() if currency_match else None
                        price = re.sub(r'[^\d]', '', text)  # Remove everything except digits
                        return price, currency

                    if price_div:
                        # Extract original price (crossed out)
                        original_tag = price_div.select_one('s.price-item--regular span.money')
                        # Extract sale price
                        sale_tag = price_div.select_one('span.price-item--sale span.money')

                        if original_tag and sale_tag:
                            original, currency = extract_price(original_tag.get_text(strip=True))
                            sale, _ = extract_price(sale_tag.get_text(strip=True))
                            product_data['original_price'] = original
                            product_data['sale_price'] = sale
                            product_data['currency'] = currency
                        elif sale_tag:
                            sale, currency = extract_price(sale_tag.get_text(strip=True))
                            product_data['original_price'] = sale
                            product_data['sale_price'] = None
                            product_data['currency'] = currency

                except Exception as e:
                    print(f"Error extracting price data: {e}")



                        # Images
                try:
                    product_data['images'] = []  # Ensure list is initialized

                    # Find all <button> tags with class 'thumbnail'
                    thumbnail_buttons = soup.find_all('button', class_='thumbnail')

                    for button in thumbnail_buttons:
                        # Find the <img> tag within the button
                        img = button.find('img')
                        if img:
                            src = img.get('src')
                            if src:
                                # Ensure full URL by adding https if missing
                                if src.startswith('//'):
                                    full_url = 'https:' + src
                                elif src.startswith('/'):
                                    full_url = urljoin(self.base_url, src)
                                else:
                                    full_url = src

                                if full_url not in product_data['images']:
                                    product_data['images'].append(full_url)

                except Exception as e:
                    print(f"Error extracting image URLs: {e}")


                # Description
                try:
                    container = soup.select_one('div.product__description')

                    if container:
                        lines = []

                        heading = container.find('h3')
                        if heading:
                            lines.append(heading.get_text(strip=True))

                        for li in container.find_all('li'):
                            text = li.get_text(strip=True)
                            if text:
                                lines.append(text)

                        product_data['description'] = '\n'.join(lines) if lines else None

                except Exception as e:
                    print(f"Error extracting description: {e}")
           
                try:
                    size_fieldset = soup.find('fieldset', class_ = lambda x: x and 'product-form__input--pill' in x)
                    if size_fieldset:
                        size_options = size_fieldset.find_all('input', {'type': 'radio'})
                        for option in size_options:
                            label = size_fieldset.find('label', {'for': option.get('id')})
                            size_label = ""
                            if label:
                                size_label = ''.join(label.find_all(string=True, recursive=False)).strip()
                            else:
                                size_label = option.get('value', '').strip()

                            is_available = 'disabled' not in option.get('class', [])

                            product_data['variants'].append({
                                'size': size_label,
                                'availability': is_available
                            })
                except Exception as e:
                    print(f"Error extracting sizes: {e}")


            except Exception as e:
                self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

            return product_data


    async def scrape_products_links(self, url):
        all_product_links = []

        # Clean URL
        split_url = urlsplit(url)
        url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, split_url.query, ''))

        try:
            self.log_info(f"Scraping page 1: {url}")
            response = await self.async_make_request(url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Select all <a> tags with href starting with '/products/'
            product_anchors = soup.select('a[href^="/products/"]')

            if not product_anchors:
                self.log_info("No product links found on the first page.")
                return []

            for anchor in product_anchors:
                href = anchor.get('href')
                if href:
                    product_url = urljoin(self.base_url, href)
                    if product_url not in all_product_links:
                        all_product_links.append(product_url)

        except Exception as e:
            self.log_error(f"Error scraping page: {e}")

        self.log_info(f"Collected {len(all_product_links)} product link(s).")
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
