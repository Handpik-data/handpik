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
from utils.LoggerConstants import HERITAGEJEWELERS_LOGGER 
from urllib.parse import urljoin, urlparse
import time


class HeritageJewelersScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://heritagejewels.com.pk/",
            logger_name=HERITAGEJEWELERS_LOGGER ,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "heritagejewelers"
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

            # --- Title ---
            try:
                product_title_tag = soup.find('h1', class_='t4s-product__title')
                if product_title_tag and product_title_tag.get_text(strip=True):
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            # --- SKU ---
            try:
                sku_span = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
                product_data['sku'] = sku_span.get_text(strip=True) if sku_span else None
            except Exception as e:
                self.log_debug(f"Exception while scraping SKU: {e}")

            # --- Prices ---
            try:
                price_container = soup.find('div', class_='t4s-product-price')
                if price_container:
                    raw_text = price_container.get_text(strip=True)
                    prices = re.findall(r'[\d,]+\.\d{2}', raw_text)
                    cleaned_prices = [float(p.replace(',', '')) for p in prices]

                    if len(cleaned_prices) == 1:
                        price_val = int(cleaned_prices[0])
                        product_data["currency"] = "Rs."
                        product_data["original_price"] = f"{price_val:,}.00"
                        product_data["sale_price"] = "null"
                    elif len(cleaned_prices) >= 2:
                        orig, sale = int(cleaned_prices[0]), int(cleaned_prices[1])
                        product_data["currency"] = "Rs."
                        product_data["original_price"] = f"{orig:,}.00"
                        product_data["sale_price"] = f"{sale:,}.00"
            except Exception as e:
                self.log_debug(f"Exception while scraping prices: {e}")

            # --- Description ---
            try:
                description_text = ""
                description_div = soup.find('div', class_='t4s-richtext_text_WchpBW t4s-pr__richtext t4s-rte')
                if description_div:
                    li_tags = description_div.find_all('li')
                    bullet_points = [li.get_text(separator=" ", strip=True) for li in li_tags]
                    if bullet_points:
                        description_text += "\n".join(f"- {point}" for point in bullet_points)
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            # --- Shipment / Delivery Info ---
            try:
                delivery_div = soup.select_one('div.t4s-pr_delivery')
                delivery_text = delivery_div.get_text(strip=True) if delivery_div else None
                product_data.setdefault('raw_data', {})['delivery'] = delivery_text
            except Exception as e:
                self.log_debug(f"Exception while scraping delivery info: {e}")

            # --- Images ---
            try:
                image_blocks = soup.find_all('div', class_='t4s_ratio t4s-product__media is-pswp-disable')
                image_urls = []

                for block in image_blocks:
                    img_tag = block.find('img')
                    if img_tag:
                        image_url = img_tag.get('data-master') or img_tag.get('data-srcset') or img_tag.get('src')

                        if image_url and ' ' in image_url:
                            image_url = image_url.split(',')[-1].split()[0]

                        if image_url:
                            if image_url.startswith("//"):
                                image_url = "https:" + image_url
                            elif image_url.startswith("/"):
                                image_url = "https://heritagejewels.com.pk" + image_url

                            image_urls.append(image_url)

                product_data["images"] = image_urls if image_urls else []
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping images: {e}")
                product_data["images"] = []

            return product_data

        except Exception as e:
            self.log_debug(f"Exception occurred during scrape_pdp: {e}")
            return None
        

    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Updated selector: all <a> tags where href contains "/products/"
                product_links = soup.find_all('a', href=True)
                product_links = [a for a in product_links if '/products/' in a['href']]

                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    product_url = urljoin(self.base_url, href)
                    if product_url not in all_product_links:
                        all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Pagination: look for a next page button (update selector as per actual tag)
                next_page_link = soup.select_one('a[rel="next"], a.pagination__item--next')
                if next_page_link and next_page_link.get('href'):
                    current_url = urljoin(self.base_url, next_page_link['href'])
                    continue
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
