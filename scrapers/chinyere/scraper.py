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
from utils.LoggerConstants import CHINYERE_LOGGER
from urllib.parse import urljoin
import time


class chinyerescraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.chinyere.pk/",
            logger_name=CHINYERE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "chinyere"
        self.all_product_links_ = []


    async def clean_price_string(self, price_str):
        if not price_str:
            return None
        if price_str.startswith("£"):
            price_str = price_str[1:]
        return price_str

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

                # Title
                try:
                    title_tag = soup.find('h1', class_="productView-title")
                    if title_tag:
                        title_span = title_tag.find('span')
                        if title_span:
                            product_data["title"] = title_span.get_text(strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's title: {e}")

                try:
                        price_div = soup.find('div', class_='price')
                        if price_div:
                            currency_symbol = None
                            sale_price = None
                            original_price = None

                            # Extract text from both sale and compare price spans
                            sale_dd = price_div.select_one('div.price__sale dd.price__last span.money')
                            compare_dd = price_div.select_one('div.price__sale dd.price__compare span.money')

                            if sale_dd and compare_dd:
                                sale_text = sale_dd.get_text(strip=True)
                                compare_text = compare_dd.get_text(strip=True)

                                sale_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', sale_text)).lstrip('.')
                                compare_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', compare_text)).lstrip('.')

                                # If the prices are the same, treat it as regular price
                                if sale_clean != compare_clean:
                                    product_data['sale_price'] = sale_clean
                                    product_data['original_price'] = compare_clean
                                    currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', sale_text)).strip()
                                else:
                                    product_data['original_price'] = sale_clean
                                    currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', sale_text)).strip()

                            elif sale_dd:
                                sale_text = sale_dd.get_text(strip=True)
                                sale_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', sale_text)).lstrip('.')
                                product_data['original_price'] = sale_clean
                                currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', sale_text)).strip()

                            elif compare_dd:
                                compare_text = compare_dd.get_text(strip=True)
                                compare_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', compare_text)).lstrip('.')
                                product_data['original_price'] = compare_clean
                                currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', compare_text)).strip()

                            else:
                                # Fallback to regular price
                                regular_dd = price_div.select_one('div.price__regular dd.price__last span.money')
                                if regular_dd:
                                    regular_text = regular_dd.get_text(strip=True)
                                    regular_clean = ''.join(filter(lambda x: x.isdigit() or x == '.', regular_text)).lstrip('.')
                                    product_data['original_price'] = regular_clean
                                    currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', regular_text)).strip()

                            if currency_symbol:
                                product_data['currency'] = currency_symbol

                except Exception as e:
                    self.log_debug(f"Error extracting prices: {str(e)}")



                try:
                    sku_div = soup.find('div', class_='productView-info-item', attrs={"data-sku": True})
                    if sku_div:
                        sku_value = sku_div.find('span', class_='productView-info-value')
                        if sku_value:
                            product_data['sku'] = sku_value.get_text(strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's SKU: {e}")


                # Description
                try:
                    description_container = soup.find('div', id='tab-description-mobile', class_='toggle-content')
                    if description_container:
                        content_div = description_container.find('div', class_='tab-popup-content')
                        if content_div:
                            product_data['description'] = content_div.get_text(separator="\n", strip=True)
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's description: {e}")

                # Images
                try:
                    image_links = []
                    image_blocks = soup.find_all('div', class_='productView-image')

                    for block in image_blocks:
                        media_div = block.find('div', class_='media')
                        if media_div:
                            href = media_div.get('href')
                            if href and any(href.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                                image_links.append(href.strip())

                        img_tag = block.find('img')
                        if img_tag:
                            src = img_tag.get('src') or img_tag.get('data-src')
                            if src:
                                image_links.append(src.strip())

                    image_links = list(set(image_links))
                    product_data['images'] = ['https:' + link if link.startswith('//') else link for link in image_links]
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's images: {e}")

                # Sizes / Variants
                try:
                    all_sizes = []
                    visible_sizes = []

                    size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
                    if size_fieldset:
                        size_labels = size_fieldset.find_all('label', class_='product-form__label')
                        for label in size_labels:
                            size_text = label.find('span', class_='text')
                            if size_text:
                                size_value = size_text.get_text(strip=True)
                                available = 'soldout' not in label.get('class', [])
                                size_data = {'size': size_value, 'availability': available}
                                all_sizes.append(size_data)
                                visible_sizes.append(size_data)

                    product_data['variants'] = all_sizes
                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product's sizes: {e}")

            except Exception as e:
                self.log_error(f"An error occurred while scraping PDP: {e}")

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

                # Get all product links on the current page
                link_tags = soup.select('a.card-link[href^="/products/"]')

                if not link_tags:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                for tag in link_tags:
                    href = tag['href']
                    product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                    all_product_links.add(product_url)

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

            page_number += 1
            if "?" not in url:
                current_url = f"{url}?page={page_number}"
            else:
                current_url = f"{url}&page={page_number}"

        self.log_info(f"Collected {len(all_product_links)} product link(s).")
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
                saved_path = await self.save_data(final_data)  # ✅ FIXED
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")
