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
from utils.LoggerConstants import ALLUREBEAUTY_LOGGER
from urllib.parse import urljoin, urlparse
import time


class AllurebeautyScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://allurebeauty.pk/",
            logger_name=ALLUREBEAUTY_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "allurebeauty"
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

            # --- TITLE ---
            try:
                product_title_tag = soup.find('h2', class_='product__title ff-heading fs-heading-2-base')
                product_data["title"] = product_title_tag.get_text(strip=True) if product_title_tag else None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            # --- BREADCRUMBS ---
            try:
                breadcrumbs = []
                breadcrumb_container = soup.find('div', class_='container')
                if breadcrumb_container:
                    ul_tag = breadcrumb_container.find('ul')
                    if ul_tag:
                        li_tags = ul_tag.find_all('li')
                        for li in li_tags:
                            a_tag = li.find('a')
                            if a_tag:
                                breadcrumbs.append(a_tag.get_text(strip=True))
                            else:
                                strong_tag = li.find('strong')
                                if strong_tag:
                                    breadcrumbs.append(strong_tag.get_text(strip=True))
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")

            # --- PRICES ---
            try:
                price_div = soup.find('div', class_='product__price ff-product-price fs-body-300')

                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    if currency:
                        text = text.replace(currency, "", 1).strip()
                    text = text.replace(",", "")
                    price = re.sub(r'^[^\d]*', '', text)
                    return price, currency

                if price_div:
                    original_price_tag = price_div.find('s', attrs={'data-compare-price': True})
                    sale_price_tag = price_div.find('span', attrs={'data-price': True})

                    original_text = original_price_tag.get_text(strip=True) if original_price_tag else ""
                    sale_text = sale_price_tag.get_text(strip=True) if sale_price_tag else ""

                    if original_text and sale_text:
                        original, currency = extract_price(original_text)
                        sale, _ = extract_price(sale_text)
                        product_data["original_price"] = original
                        product_data["sale_price"] = sale
                        product_data["currency"] = currency
                    elif sale_text and not original_text:
                        price, currency = extract_price(sale_text)
                        product_data["original_price"] = price
                        product_data["sale_price"] = None
                        product_data["currency"] = currency
            except Exception as e:
                print(f"Error extracting price data: {e}")

            # --- SKU ---
            try:
                sku_div = soup.find('div', class_='product__sku fs-body-50 t-opacity-70')
                sku_text = None
                if sku_div:
                    full_text = sku_div.get_text(strip=True)
                    if full_text.startswith("SKU:"):
                        sku_text = full_text.split("SKU:")[1].strip()
                product_data["sku"] = sku_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping SKU: {e}")

            # --- VARIANTS ---
            variants = []
            try:
                sizes = []
                size_fieldset = soup.find('fieldset', class_='product-form__input--pill')
                if size_fieldset:
                    input_tags = size_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in input_tags:
                        size_value = input_tag.get('value', '').strip()
                        if size_value:
                            input_classes = input_tag.get('class', [])
                            is_disabled = 'disabled' in input_classes
                            availability = 'unavailable' if is_disabled else 'available'
                            sizes.append({
                                'size': size_value,
                                'availability': availability
                            })
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes: {e}")

            colors = [{'availability': 'available'}]
            for size in sizes:
                combined_availability = 'false' if size['availability'] == 'unavailable' else 'true'
                variants.append({
                    'size': size['size'],
                    'availability': combined_availability
                })
            product_data['variants'] = variants

            # --- IMAGES ---
            try:
                product_images = []
                thumbnails_ul = soup.find('ul', class_='product-thumbnails__items')

                if thumbnails_ul:
                    image_tags = thumbnails_ul.find_all('img', class_='image__img')
                else:
                    image_tags = soup.find_all('img', class_='image__img')  # Fallback

                for img in image_tags:
                    srcset = img.get('srcset')
                    if srcset:
                        last_src = srcset.strip().split(',')[-1].split()[0]
                        if last_src.startswith('//'):
                            last_src = 'https:' + last_src
                        product_images.append(last_src)
                    else:
                        src = img.get('src')
                        if src:
                            if src.startswith('//'):
                                src = 'https:' + src
                            product_images.append(src)

                product_data['images'] = list(set(product_images))

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

            # --- DESCRIPTION ---
            try:
                description_text = ""
                desc_div = soup.find('div', id='accordion-content-description')
                if desc_div:
                    p_tags = desc_div.find_all('p')
                    desc_lines = [p.get_text(" ", strip=True) for p in p_tags if p.get_text(strip=True)]
                    description_text = " ".join(desc_lines).strip()
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            # --- ACCORDION DATA ---
            try:
                raw_data = {}

                def extract_accordion(section_id, key):
                    div = soup.find('div', id=section_id)
                    raw_data[key] = div.get_text(" ", strip=True) if div else None

                extract_accordion("accordion-content-accordion-1", "shipping_and_return")
                extract_accordion("accordion-content-accordion-2", "authenticity_info")
                extract_accordion("accordion-content-accordion-3", "rewards_info")

                product_data["raw_data"].update(raw_data)
            except Exception as e:
                product_data["raw_data"].update({
                    "shipping_and_return": None,
                    "authenticity_info": None,
                    "rewards_info": None
                })
                print(f"Error extracting accordion data: {e}")

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data



    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Select <a> tags with class 'product-item__image-link'
                product_links = soup.select('a.product-item__image-link')

                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                # Extract and add product URLs
                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Pagination: look for next page link (update selector as per your site's pagination)
                next_page_link = soup.select_one('a.next')  # Adjust if your pagination class is different
                if next_page_link:
                    next_href = next_page_link.get('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                        continue
                    else:
                        self.log_info("Next page href not found. Stopping pagination.")
                        break
                else:
                    self.log_info("No next page link found. Finished scraping all pages.")
                    break

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
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
