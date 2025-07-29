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
from utils.LoggerConstants import Firststep_LOGGER
from urllib.parse import urljoin, urlparse
import time


class firstStepScrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://1ststep.pk/",
            logger_name=Firststep_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "1ststep"
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
                product_title_tag = soup.find('h1', class_="product__title")
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            try:
                sku_element = soup.select_one('span.variant-sku')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product SKU: {e}")

            try:
                price_wrapper = soup.find('div', class_='product__price')
                if price_wrapper:
                    sale_price_tag = price_wrapper.find('span', class_='product__price--regular product__price--sale')
                    original_price_tag = price_wrapper.find('s', class_='product__price--compare')

                    currency = None

                    if sale_price_tag and original_price_tag:
                        sale_money_tag = sale_price_tag.find('span', class_='money')
                        original_money_tag = original_price_tag.find('span', class_='money')

                        sale_price_str = sale_money_tag.get_text(strip=True) if sale_money_tag else None
                        original_price_str = original_money_tag.get_text(strip=True) if original_money_tag else None

                        product_data['sale_price'] = re.sub(r'[^\d]', '', sale_price_str) if sale_price_str else None
                        product_data['original_price'] = re.sub(r'[^\d]', '', original_price_str) if original_price_str else None

                    elif sale_price_tag and not original_price_tag:
                        sale_money_tag = sale_price_tag.find('span', class_='money')
                        sale_price_str = sale_money_tag.get_text(strip=True) if sale_money_tag else None

                        product_data['sale_price'] = re.sub(r'[^\d]', '', sale_price_str) if sale_price_str else None
                        product_data['original_price'] = None

                    else:
                        single_price_tag = price_wrapper.find('span', class_='money')
                        if single_price_tag:
                            price_str = single_price_tag.get_text(strip=True)
                            product_data['original_price'] = re.sub(r'[^\d]', '', price_str)
                            product_data['sale_price'] = None
                        else:
                            product_data['original_price'] = None
                            product_data['sale_price'] = None

                    price_text = None
                    if sale_price_tag:
                        sale_money_tag = sale_price_tag.find('span', class_='money')
                        price_text = sale_money_tag.get_text(strip=True) if sale_money_tag else None
                    elif original_price_tag:
                        original_money_tag = original_price_tag.find('span', class_='money')
                        price_text = original_money_tag.get_text(strip=True) if original_money_tag else None

                    if price_text:
                        match = re.match(r'([^\d\s]+)', price_text)
                        if match:
                            currency = match.group(1)

                    product_data['currency'] = currency

                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")

            try:
                breadcrumbs_nav = soup.find('nav', class_='breadcrumbs')
                category_path = []

                if breadcrumbs_nav:
                    breadcrumb_links = breadcrumbs_nav.find_all('a', class_='breadcrumbs__link')
                    for link in breadcrumb_links:
                        if link.get_text(strip=True).lower() != "home":
                            category_path.append(link.get_text(strip=True))

                    current_span = breadcrumbs_nav.find('span', class_='breadcrumbs__current')
                    if current_span:
                        category_path.append(current_span.get_text(strip=True))

                product_data["category"] = category_path if category_path else None

            except Exception as e:
                self.log_debug(f"Error extracting category path list: {e}")
                product_data["category"] = None

            try:
                breadcrumbs_nav = soup.find('nav', class_='breadcrumbs')
                breadcrumbs = []

                if breadcrumbs_nav:
                    breadcrumb_links = breadcrumbs_nav.find_all('a', class_='breadcrumbs__link')
                    for link in breadcrumb_links:
                        text = link.get_text(strip=True)
                        if text.lower() != "home":
                            breadcrumbs.append(text)

                    current_span = breadcrumbs_nav.find('span', class_='breadcrumbs__current')
                    if current_span:
                        breadcrumbs.append(current_span.get_text(strip=True))

                product_data['attributes']['breadcrumbs'] = breadcrumbs if breadcrumbs else None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = None

            variants = []

            try:
                colors = []
                color_fieldset = soup.find('fieldset', class_='radio__fieldset mry-hideColor radio__fieldset--rectangle')
                if color_fieldset:
                    color_inputs = color_fieldset.find_all('input', class_='swatch__input')
                    for input_tag in color_inputs:
                        color_value = input_tag.get('value', '').strip()
                        if color_value:
                            availability = 'unavailable' if input_tag.has_attr('disabled') else 'available'
                            colors.append({'color': color_value, 'availability': availability})
            except Exception as e:
                self.log_error(f"Error extracting colors: {e}")

            try:
                sizes = []
                size_fieldset = soup.find('fieldset', class_='radio__fieldset radio__fieldset--rectangle')
                if size_fieldset:
                    size_inputs = size_fieldset.find_all('input', class_='radio__input')
                    for input_tag in size_inputs:
                        size_value = input_tag.get('value', '').strip()
                        if size_value:
                            availability = 'unavailable' if input_tag.has_attr('disabled') else 'available'
                            sizes.append({'size': size_value, 'availability': availability})
            except Exception as e:
                self.log_debug(f"Error extracting sizes: {e}")

            for color in colors:
                for size in sizes:
                    combined_availability = (
                        'false'
                        if color['availability'] == 'unavailable' or size['availability'] == 'unavailable'
                        else 'true'
                    )
                    variants.append({
                        'size': size['size'],
                        'color': color['color'],
                        'availability': combined_availability
                    })

            product_data['variants'] = variants

            try:
                image_links = soup.find_all('a', class_='product-single__media-link')

                product_images = []

                for link in image_links:
                    img_url = link.get('href')
                    if img_url:
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        product_images.append(img_url)

                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

            try:
                description_section = soup.find('div', class_='ProductMeta__Description')

                if description_section:
                    paragraphs = description_section.find_all('p')

                    product_description_text = ""
                    care_instructions = ""

                    for p in paragraphs:
                        text = p.get_text(separator="\n", strip=True)

                        if 'CARE INSTRUNCTIONS' in text.upper():
                            care_instructions = text.replace('CARE INSTRUNCTIONS', '').strip()
                        else:
                            product_description_text += text + "\n"

                    product_data['description'] = product_description_text.strip()
                    product_data['raw_data'] = {
                        'care_instructions': care_instructions.strip() if care_instructions else None
                    }
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description and care instructions: {e}")
                product_data['description'] = ""
                product_data['raw_data'] = {
                    'care_instructions': None
                }

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
                product_links = soup.select('a.product__media__holder[href^="/collections/"]')

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
