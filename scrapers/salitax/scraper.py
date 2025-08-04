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
from utils.LoggerConstants import SALITEX_LOGGER
from urllib.parse import urljoin, urlparse
import time


class SalitaxScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://salitexonline.com/",
            logger_name=SALITEX_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "salitex"
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
            'category': [],
            'product_url': product_link,
            'variants': [],
            'attributes': {},
            'raw_data': {}
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # ---------------------------------
            # Title
            # ---------------------------------
            try:
                product_title_tag = soup.find('h1', class_='product__title heading-size-2')
                if product_title_tag:
                    span_tag = product_title_tag.find('span')
                    product_data["title"] = span_tag.get_text(strip=True) if span_tag else product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Title scrape error: {e}")

            # ---------------------------------
            # Description (tab-content or fallback)
            # ---------------------------------
            try:
                desc_div = soup.find('div', class_='tab-content tab-content-0 current rte')
                if desc_div:
                    desc_parts = [p.get_text(separator=" ", strip=True) for p in desc_div.find_all('p')]
                    li_parts = [li.get_text(separator=" ", strip=True) for li in desc_div.find_all('li')]
                    description_text = "\n".join(desc_parts + li_parts).strip()
                    product_data['description'] = description_text
                else:
                    # fallback to accordion content
                    accordion_content = soup.find('div', class_='accordion__content')
                    if accordion_content:
                        desc_parts = []
                        for p in accordion_content.find_all('p'):
                            spans = p.find_all('span')
                            if spans:
                                for span in spans:
                                    desc_parts.append(span.get_text(separator=" ", strip=True))
                            else:
                                desc_parts.append(p.get_text(separator=" ", strip=True))
                        product_data['description'] = "\n".join(desc_parts).strip()
            except Exception as e:
                self.log_debug(f"Description scrape error: {e}")

            # ---------------------------------
            # Attributes
            # ---------------------------------
            try:
                attr_div = soup.find('div', class_='accordion__content')
                if attr_div:
                    span_tag = attr_div.find('span', class_='metafield-multi_line_text_field')
                    if span_tag:
                        lines = span_tag.decode_contents().split('<br>')
                        attributes = [BeautifulSoup(line, "html.parser").get_text(strip=True) for line in lines if line.strip()]
                        product_data['attributes']['product_details'] = attributes
            except Exception as e:
                self.log_debug(f"Attributes scrape error: {e}")

            # ---------------------------------
            # Price (Handles both sale & non-sale)
            # ---------------------------------
            try:
                def parse_currency_and_price(text):
                    match = re.match(r'([^0-9]+)?([\d,]+\.?\d*)', text.strip())
                    if not match:
                        return None, None
                    currency_symbol, amount = match.groups()
                    amount = amount.replace(',', '')
                    try:
                        return currency_symbol.strip(), float(amount)
                    except:
                        return currency_symbol.strip(), None

                price_block = soup.find('div', class_='product__price')
                if price_block:
                    sale_span = price_block.find('span', class_='product__price--sale')
                    strike_tag = price_block.find('s', class_='product__price--strike')
                    primary_span = price_block.find('span', attrs={'data-product-price': True})

                    if sale_span and strike_tag:
                        # Product is on sale
                        cur1, sp = parse_currency_and_price(sale_span.get_text(strip=True))
                        cur2, op = parse_currency_and_price(strike_tag.get_text(strip=True))
                        product_data['currency'] = cur1 or cur2
                        product_data['sale_price'] = sp
                        product_data['original_price'] = op

                    elif primary_span:
                        # Not on sale
                        currency, price = parse_currency_and_price(primary_span.get_text(strip=True))
                        product_data['currency'] = currency
                        product_data['original_price'] = price
                        product_data['sale_price'] = None

                    elif sale_span:
                        # Fallback if only sale price shown (no strikethrough)
                        currency, price = parse_currency_and_price(sale_span.get_text(strip=True))
                        product_data['currency'] = currency
                        product_data['original_price'] = price
                        product_data['sale_price'] = None
            except Exception as e:
                self.log_debug(f"Price scrape error: {e}")

            # ---------------------------------
            # Breadcrumb Categories
            # ---------------------------------
            try:
                breadcrumbs_div = soup.find('div', class_='breadcrumbs')
                categories = []
                if breadcrumbs_div:
                    li_tags = breadcrumbs_div.find_all('li')
                    for li in li_tags:
                        if 'home' in li.get('class', []):
                            continue
                        a = li.find('a')
                        strong = li.find('strong')
                        if a:
                            categories.append(a.get_text(strip=True))
                        elif strong:
                            categories.append(strong.get_text(strip=True))
                product_data["category"] = categories
            except Exception as e:
                self.log_debug(f"Breadcrumb scrape error: {e}")



            try:
                availability = True  # Default assumption

                sold_out_btn = soup.find('button', {
                    'id': lambda x: x and 'AddToCart' in x,
                    'disabled': True
                })

                if sold_out_btn and 'Sold Out' in sold_out_btn.get_text(strip=True):
                    availability = None

                product_data['availability'] = availability

            except Exception as e:
                self.log_debug(f"Exception while checking availability: {e}")


            # ---------------------------------
            # Variants (sizes)
            # ---------------------------------
            try:
                sizes = []
                fieldset = soup.find('fieldset', class_='variant-picker__option v-stack gap-2')
                if fieldset:
                    inputs = fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in inputs:
                        input_id = input_tag.get('id', '').strip()
                        if input_id:
                            label = fieldset.find('label', {'for': input_id})
                            if label:
                                size_span = label.find('span')
                                size_text = size_span.get_text(strip=True) if size_span else ''
                                is_disabled = 'is-disabled' in label.get('class', [])
                                availability = 'unavailable' if is_disabled else 'available'
                                sizes.append({'size': size_text, 'availability': availability})
                product_data['variants'] = [{'size': s['size'], 'availability': 'false' if s['availability'] == 'unavailable' else 'true'} for s in sizes]
            except Exception as e:
                self.log_debug(f"Variants scrape error: {e}")

            # ---------------------------------
            # Images (high quality with srcset)
            # ---------------------------------
            try:
                product_images = []
                figure_tags = soup.find_all('figure', class_='image-wrapper')
                for fig in figure_tags:
                    img = fig.find('img')
                    if img:
                        srcset = img.get('srcset')
                        if srcset:
                            urls = [s.strip().split(' ')[0] for s in srcset.split(',')]
                            src = urls[-1] if urls else None
                        else:
                            src = img.get('data-src') or img.get('src')
                        if src:
                            product_images.append('https:' + src if not src.startswith('http') else src)
                product_data['images'] = list(set(product_images))
            except Exception as e:
                self.log_debug(f"Images scrape error: {e}")

            # ---------------------------------
            # RAW Data: Delivery, Return & Care Instructions
            # ---------------------------------
            try:
                # Delivery Dates
                delivery_div = soup.find('div', class_='accordion__content')
                if delivery_div:
                    delivery_p = delivery_div.find('p', id='deliveryDates')
                    if delivery_p:
                        from_date = delivery_p.find('span', id='fromDate')
                        to_date = delivery_p.find('span', id='toDate')
                        product_data['raw_data']['estimated_dispatch_date'] = f"{from_date.get_text(strip=True)} - {to_date.get_text(strip=True)}" if from_date and to_date else None

                # Return & Care
                toggle_contents = soup.find_all('div', class_='toggle-ellipsis__content')
                if toggle_contents:
                    if len(toggle_contents) >= 1:
                        ret = toggle_contents[0].get_text(separator=" ", strip=True)
                        product_data['raw_data']['return_exchange_policy'] = ret
                    if len(toggle_contents) >= 2:
                        care = toggle_contents[1].get_text(separator=" ", strip=True)
                        product_data['raw_data']['care_instructions'] = care
            except Exception as e:
                self.log_debug(f"Raw data scrape error: {e}")

        except Exception as e:
            self.log_debug(f"PDP scrape failed: {e}")

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

                # ✅ Updated selector: select <a> tags with class 'product-link'
                product_links = soup.select('a.product-link')

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

                # Pagination: look for next page link (update selector according to site pagination structure)
                next_page_link = soup.select_one('a.next')
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
