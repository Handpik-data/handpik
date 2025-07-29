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
from utils.LoggerConstants import PANACHE_LOGGER
from urllib.parse import urljoin, urlparse
import time


class PanacheScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://panachebymona.com/",
            logger_name=PANACHE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "panache"
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
                'care_instructions': None
            }
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                product_title_tag = soup.find('h1', class_="product__section-title product-title")
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            try:
                sku_element = soup.find('span', class_="product__sku-value js-product-sku")
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product SKU: {e}")

            try:
                price_wrapper = soup.find('div', id='product-price')
                if price_wrapper:
                    original_price = None
                    sale_price = None
                    currency = None

                    sale_price_tag = price_wrapper.find('span', class_='price-item price-item--sale')
                    if sale_price_tag:
                        cvc_money = sale_price_tag.find('span', class_='cvc-money')
                        if cvc_money:
                            sale_price_str = cvc_money.get_text(strip=True)
                            sale_price = re.sub(r'[^\d]', '', sale_price_str)
                            match = re.match(r'([^\d\s]+)', sale_price_str)
                            if match:
                                currency = match.group(1)

                    original_price_tag = price_wrapper.find_all('span', class_='price-item price-item--regular')
                    if original_price_tag:
                        if len(original_price_tag) > 1:
                            cvc_money = original_price_tag[1].find('span', class_='cvc-money')
                            if cvc_money:
                                original_price_str = cvc_money.get_text(strip=True)
                                original_price = re.sub(r'[^\d]', '', original_price_str)
                                if not currency:
                                    match = re.match(r'([^\d\s]+)', original_price_str)
                                    if match:
                                        currency = match.group(1)
                        else:
                            cvc_money = original_price_tag[0].find('span', class_='cvc-money')
                            if cvc_money:
                                original_price_str = cvc_money.get_text(strip=True)
                                original_price = re.sub(r'[^\d]', '', original_price_str)
                                if not currency:
                                    match = re.match(r'([^\d\s]+)', original_price_str)
                                    if match:
                                        currency = match.group(1)

                    product_data['sale_price'] = sale_price
                    product_data['original_price'] = original_price
                    product_data['currency'] = currency
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")

            try:
                breadcrumb = soup.find('div', id='breadcrumb')
                categories = []

                if breadcrumb:
                    breadcrumb_links = breadcrumb.find_all('a')
                    for link in breadcrumb_links:
                        text = link.get_text(strip=True)
                        if text != 'Home':
                            categories.append(text)

                    page_title = breadcrumb.find('span', class_='page-title')
                    if page_title:
                        categories.append(page_title.get_text(strip=True))

                product_data['category'] = categories

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumb categories: {e}")

            try:
                breadcrumbs = []
                breadcrumb_div = soup.find('div', id='breadcrumb')

                if breadcrumb_div:
                    breadcrumb_links = breadcrumb_div.find_all('a')
                    for link in breadcrumb_links:
                        text = link.get_text(strip=True)
                        if text:
                            breadcrumbs.append(text)

                    page_title_span = breadcrumb_div.find('span', class_='page-title')
                    if page_title_span:
                        page_title = page_title_span.get_text(strip=True)
                        if page_title:
                            breadcrumbs.append(page_title)

                product_data['attributes']['breadcrumbs'] = breadcrumbs

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []

            variants = []

            try:
                sizes = []
                size_divs = soup.select('div.swatches__container div.js-swatch-element')

                for div in size_divs:
                    input_tag = div.find('input', class_='swatches__form--input')
                    label_tag = div.find('label', class_='swatches__form--label')

                    if input_tag and label_tag:
                        size_value = input_tag.get('value', '').strip()

                        # Check if div has 'soldout' class
                        soldout_class = 'soldout' in div.get('class', [])

                        # Check if sold out image is visible (exists and not hidden)
                        sold_out_img_tag = label_tag.find('img', class_='swatches__sold-out--image')
                        sold_out_img_visible = False
                        if sold_out_img_tag:
                            # Check if img has inline style display:none or hidden attribute
                            style_attr = sold_out_img_tag.get('style', '')
                            if 'display:none' not in style_attr.replace(" ", ""):
                                sold_out_img_visible = True

                        # Determine availability
                        availability = 'false' if soldout_class or sold_out_img_visible else 'true'

                        sizes.append({'size': size_value, 'availability': availability})

            except Exception as e:
                self.log_debug(f"Error extracting sizes: {e}")

            for size in sizes:
                variants.append({
                    'size': size['size'],
                    'availability': size['availability']
                })

            product_data['variants'] = variants


            try:
                image_divs = soup.find_all('div', class_='product-single__thumbnail product-single__thumbnail--template--19725956808986__main js-thumb-item-img-wrap')
                product_images = []

                for div in image_divs:
                    img_tag = div.find('img')
                    if img_tag:
                        img_url = img_tag.get('src')
                        if img_url:
                            if img_url.startswith('//'):
                                img_url = 'https:' + img_url
                            if 'width=' in img_url:
                                img_url = img_url.split('width=')[0] + 'width=1000'
                            product_images.append(img_url)

                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

            try:
                description_section = soup.find('div', class_='tab tab--template--19725956808986__main--10 tabbed-block rte')
                if description_section:
                    paragraphs = description_section.find_all('p')
                    product_description_text = ""

                    for p in paragraphs:
                        text = p.get_text(separator="\n", strip=True)
                        product_description_text += text + "\n"

                    product_data['description'] = product_description_text.strip()
                else:
                    product_data['description'] = ""

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            try:
                product_data['raw_data'] = {}

                delivery_section = soup.find('div', class_='tab tab--template--19725956808986__main--12 tabbed-block rte')
                if delivery_section:
                    paragraphs = delivery_section.find_all('p')
                    delivery_text = ""
                    for p in paragraphs:
                        text = p.get_text(separator="\n", strip=True)
                        delivery_text += text + "\n"
                    product_data['raw_data']['delivery_time'] = delivery_text.strip()
                else:
                    product_data['raw_data']['delivery_time'] = None

                care_section = soup.find('div', class_='tab tab--template--19725956808986__main--13 tabbed-block rte')
                if care_section:
                    care_text = care_section.get_text(separator="\n", strip=True)
                    product_data['raw_data']['care_instructions'] = care_text.strip()
                else:
                    product_data['raw_data']['care_instructions'] = None

                disclaimer_section = soup.find('div', class_='tab tab--template--19725956808986__main--14 tabbed-block rte')
                if disclaimer_section:
                    disclaimer_text = disclaimer_section.get_text(separator="\n", strip=True)
                    product_data['raw_data']['disclaimer'] = disclaimer_text.strip()
                else:
                    product_data['raw_data']['disclaimer'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping delivery, care instructions, or disclaimer: {e}")
                product_data['raw_data']['delivery_time'] = None
                product_data['raw_data']['care_instructions'] = None
                product_data['raw_data']['disclaimer'] = None

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

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

                # Updated selector for new structure
                product_links = soup.select('a[href*="/collections/"][href*="/products/"]')

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
