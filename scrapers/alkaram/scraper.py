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
from utils.LoggerConstants import ALKARAM_LOGGER
from urllib.parse import urljoin, urlparse
import time


class AlkaramScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.alkaramstudio.com/",
            logger_name=ALKARAM_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "alkaramstudio"
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
            "attributes": {},
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                title_tag = soup.select_one('h1.product-title.h5')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting title: {str(e)}', 'product_link': product_link}

            try:
                sku_element = soup.select_one('div.product-info__block-item[data-block-type="sku"] variant-sku')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True).replace("SKU:", "").strip()
            except Exception as e:
                return {'error': f'Exception occurred while extracting SKU: {str(e)}', 'product_link': product_link}

            try:
                image_elements = soup.select('img.object-contain')
                for img in image_elements:
                    src = img.get('src')
                    if src and src not in product_data['images']:
                        full_url = urljoin(self.base_url, src)
                        product_data['images'].append(full_url)
            except Exception as e:
                return {'error': f'Exception occurred while extracting images: {str(e)}', 'product_link': product_link}

            try:
                breadcrumb = soup.find('nav', class_='t4s-pr-breadcrumb')
                breadcrumb_path = []
                if breadcrumb:
                    items = breadcrumb.find_all(['a', 'span'])
                    for item in items:
                        text = item.get_text(strip=True)
                        if text and text != 'Home':
                            breadcrumb_path.append(text)
                product_data['category'] = breadcrumb_path
            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}', 'product_link': product_link}

            try:
                price_list = soup.find("price-list", class_="price-list--product")
                original_price, sale_price, currency = None, None, None

                if price_list:
                    sale_tag = price_list.find("sale-price")
                    if sale_tag:
                        sale_price_text = sale_tag.get_text(strip=True)
                        sale_price = ''.join(filter(str.isdigit, sale_price_text))
                        if "PKR" in sale_price_text.upper():
                            currency = "PKR"

                    compare_tag = price_list.find("compare-at-price")
                    if compare_tag:
                        original_price_text = compare_tag.get_text(strip=True)
                        original_price = ''.join(filter(str.isdigit, original_price_text))
                        if not currency and "PKR" in original_price_text.upper():
                            currency = "PKR"

                    if not original_price and sale_price:
                        original_price = sale_price
                    if original_price and sale_price and original_price == sale_price:
                        sale_price = None

                product_data['original_price'] = original_price
                product_data['sale_price'] = sale_price
                product_data['currency'] = currency
            except Exception as e:
                return {'error': f'Exception occurred while extracting prices: {str(e)}'}

            try:
                description_container = soup.select_one('div.accordion__content.prose')
                if description_container:
                    product_data['description'] = description_container.get_text(
                        separator="\n", strip=True
                    )
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's description: {e}")

            try:
                breadcrumb_nav = soup.select_one('nav.t4s-pr-breadcrumb')
                if breadcrumb_nav:
                    breadcrumb_items = []
                    breadcrumb_links = breadcrumb_nav.find_all('a')
                    for link in breadcrumb_links:
                        breadcrumb_items.append(link.get_text(strip=True))
                    breadcrumb_span = breadcrumb_nav.find('span')
                    if breadcrumb_span:
                        breadcrumb_items.append(breadcrumb_span.get_text(strip=True))
                    product_data['attributes']['breadcrumbs'] = breadcrumb_items
            except Exception as e:
                return {'error': f'Exception occurred while extracting breadcrumbs: {str(e)}'}
            
            try:
                availability_tag = soup.select_one('div.product-info__block-item variant-inventory span')
                if availability_tag:
                    availability_text = availability_tag.get_text(strip=True).lower()
                    product_data['availability'] = "in stock" in availability_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping availability: {e}")


            try:
                shipping_div = soup.find('div', id='t4s_tab_c1f78054-ee99-4f40-89e2-f342a6fcebc3')
                if shipping_div:
                    product_data['raw_data']['shipping_and_handling'] = shipping_div.get_text(separator="\n", strip=True)
                disclaimer_div = soup.find('div', class_='tab--disclaimer')
                if disclaimer_div:
                    product_data['raw_data']['disclaimer'] = disclaimer_div.get_text(separator=' ', strip=True)
            except Exception as e:
                return {'error': f'Exception occurred while extracting shipping/handling or disclaimer: {str(e)}'}

            try:
                material_fieldset = soup.find('fieldset', class_='variant-picker__option v-stack gap-2')
                if material_fieldset:
                    legend = material_fieldset.find('legend')
                    if legend and "Fabric" in legend.get_text(strip=True):
                        span_tag = material_fieldset.find('span')
                        if span_tag:
                            product_data['raw_data']['material'] = span_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's material: {e}")

            try:
                variants = []

                fieldsets = soup.select("fieldset.variant-picker__option")

                colors, fabrics, sizes = [], [], []

                for fs in fieldsets:
                    legend = fs.find("legend")
                    legend_text = legend.get_text(strip=True) if legend else ""

                    if "fabric" in legend_text.lower():
                        group_type = "fabric"
                    elif "color" in legend_text.lower():
                        group_type = "color"
                    else:
                        group_type = "size"

                    inputs = fs.select("input[type='radio']")
                    for inp in inputs:
                        label = fs.find("label", {"for": inp.get("id")})
                        value = None
                        if label:
                            sr_span = label.select_one("span.sr-only")
                            if sr_span:  
                                value = sr_span.get_text(strip=True)
                            else:
                                value = label.get_text(strip=True)
                        if value:
                            is_disabled = "is-disabled" in (label.get("class", []) if label else [])
                            item = {"value": value, "availability": not is_disabled}
                            if group_type == "fabric":
                                fabrics.append(item)
                            elif group_type == "color":
                                colors.append(item)
                            else:
                                sizes.append(item)

                if not fabrics:
                    fabrics = [{"value": "null", "availability": True}]
                if not colors:
                    colors = [{"value": "null", "availability": True}]
                if not sizes:
                    sizes = [{"value": "null", "availability": True}]

                for s in sizes:
                    for f in fabrics:
                        for c in colors:
                            availability = s["availability"] and f["availability"] and c["availability"]
                            variants.append({
                                "size": s["value"],
                                "fabric": f["value"],
                                "color": c["value"],
                                "availability": availability
                            })

                product_data['variants'] = variants

            except Exception as e:
                return {'error': f'Exception occurred while extracting variants: {str(e)}'}


        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

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

                product_links = soup.select('a.product-card__media')

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = f"{self.base_url}{href}" if href.startswith("/") else href
                        all_product_links.append(product_url)

                        if len(all_product_links) >= 5:
                            self.log_info("Collected 5 product links. Stopping.")
                            return all_product_links

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