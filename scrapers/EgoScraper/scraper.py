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
from utils.LoggerConstants import Ego_LOGGER
from urllib.parse import urljoin
import time


class EgoScrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://wearego.com/",
            logger_name=Ego_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "ego"
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
            "attributes": {
                        'breadcrumbs': None,
                    },
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                product_title_tag = soup.find('h1', class_='product-single__title ttlTxt tt-u mb15')
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            try:
                sku_element = (
                    soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value') or
                    soup.select_one('div.product-sku span.variant-sku') or
                    soup.select_one('span.product-single__sku')
                )
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product SKU: {e}")

            try:
                price_div = (
                    soup.find('div', id=lambda x: x and x.startswith('pricetemplate')) or
                    soup.find('div', class_='psinglePriceWr')
                )

                if price_div:
                    sale_price_tag = price_div.select_one('span.psinglePrice.sale .money') or price_div.select_one('span.psinglePrice .money')
                    if sale_price_tag:
                        price_text = sale_price_tag.get_text(strip=True).replace("Rs.", "").replace(",", "")
                        try:
                            product_data['sale_price'] = float(price_text)
                        except ValueError:
                            product_data['sale_price'] = None

                    original_price_tag = price_div.select_one('s.psinglePrice .money')
                    if original_price_tag:
                        price_text = original_price_tag.get_text(strip=True).replace("Rs.", "").replace(",", "")
                        try:
                            product_data['original_price'] = float(price_text)
                        except ValueError:
                            product_data['original_price'] = None

                    if not product_data.get('original_price') and product_data.get('sale_price'):
                        product_data['original_price'] = product_data['sale_price']
                        product_data['sale_price'] = None

                    product_data['currency'] = "PKR"
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping prices: {e}")
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = "PKR"

            try:
                image_links = soup.select('a.pr_photo') or soup.select('div.pr_thumbs_item a.gitem-img')
                for a_tag in image_links:
                    zoom_src = a_tag.get('data-zoom') or a_tag.get('href')
                    if zoom_src:
                        full_url = urljoin('https:', zoom_src)
                        if full_url not in product_data['images']:
                            product_data['images'].append(full_url)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

            try:
                breadcrumbs = []
                breadcrumb_nav = soup.select_one('nav.page-width.breadcrumbs')
                if breadcrumb_nav:
                    for element in breadcrumb_nav.find_all(['a', 'span'], recursive=False):
                        if element.name == 'span' and 'symbol' in element.get('class', []):
                            continue
                        text = element.get_text(strip=True)
                        if text:
                            breadcrumbs.append(text)
                product_data['attributes']['breadcrumbs'] = " > ".join(breadcrumbs)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = ""

            try:
                stock_element = soup.select_one('div.product-stock span.stockLbl') or soup.select_one('span.stockLbl.instock')
                if stock_element:
                    stock_text = stock_element.get_text(strip=True).lower()
                    product_data['availability'] = 'out of stock' not in stock_text
                else:
                    product_data['availability'] = False
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping stock availability: {e}")
                product_data['availability'] = False

            try:
                breadcrumb_nav = soup.select_one('nav.page-width.breadcrumbs')
                category = None
                if breadcrumb_nav:
                    breadcrumb_items = breadcrumb_nav.find_all(['a', 'span'], recursive=False)
                    visible_items = [el for el in breadcrumb_items if el.name in ['a', 'span'] and 'symbol' not in el.get('class', [])]
                    if len(visible_items) >= 2:
                        category = visible_items[1].get_text(strip=True)
                product_data['category'] = category
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping category from breadcrumbs: {e}")
                product_data['category'] = None

            try:
                desc_div = soup.select_one('div.product-single__description.rte')
                if desc_div:
                    for br in desc_div.find_all('br'):
                        br.replace_with('\n')
                    raw_text = desc_div.get_text(separator='\n')
                    lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
                    description_text = '\n'.join(lines)
                    product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product description: {e}")
                product_data['description'] = ""

            try:
                size_inputs = soup.find_all("input", {"name": "size"})
                size_info_list = []

                for input_tag in size_inputs:
                    size = input_tag["value"]
                    variant_id = input_tag.get("data-variant-id")
                    if variant_id:
                        variant_url = f"{product_link}?variant={variant_id}"
                        variant_response = requests.get(variant_url)
                        variant_soup = BeautifulSoup(variant_response.text, 'html.parser')
                        add_to_cart_button = variant_soup.find("button", {"id": "AddToCart-template--16869896716541__product"})
                        if add_to_cart_button:
                            is_disabled = add_to_cart_button.has_attr("disabled")
                            is_available = not is_disabled
                        else:
                            is_available = False

                        size_info_list.append({
                            "size": size,
                            "availability": is_available
                        })

                product_data['variants'] = size_info_list
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping size availability: {e}")
                product_data['variants'] = []

            try:
                shipping_div = soup.select_one('div.product__policies')
                if shipping_div:
                    shipping_text = shipping_div.get_text(strip=True)
                    product_data['raw_data']['shipping_policy'] = shipping_text

                delivery_p = soup.select_one('p.shippingMsg.mb25')
                if delivery_p:
                    delivery_text = delivery_p.get_text(strip=True)
                    product_data['raw_data']['delivery_estimate'] = delivery_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping shipping and delivery info: {e}")
                product_data['raw_data']['shipping_policy'] = None
                product_data['raw_data']['delivery_estimate'] = None

          

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

                product_links = soup.select('a.gimg-link[href^="/products/"]')

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        all_product_links.append(product_url)

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
