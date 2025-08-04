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
from utils.LoggerConstants import VITALITY_LOGGER
from urllib.parse import urljoin, urlparse
import time


class VitalityScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://vitalitypk.com/",
            logger_name=VITALITY_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Vitality"
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

            # ------- TITLE -------
            try:
                product_title_wrapper = soup.find('div', class_='productView-moreItem')
                if product_title_wrapper:
                    product_title_tag = product_title_wrapper.find('h1', class_='productView-title')
                    if product_title_tag:
                        product_title_span = product_title_tag.find('span')
                        if product_title_span and product_title_span.get_text(strip=True):
                            product_data["title"] = product_title_span.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            # ------- BREADCRUMBS -------
            try:
                breadcrumbs = []
                breadcrumb_container = soup.find('ol', class_='breadcrumbs__list')
                if breadcrumb_container:
                    a_tags = breadcrumb_container.find_all('a', class_='breadcrumbs__link')
                    for a_tag in a_tags:
                        crumb = a_tag.get_text(strip=True)
                        breadcrumbs.append(crumb)
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []

            # ------- SKU -------
            try:
                sku_text = None
                sku_container = soup.find('p', class_='ProductMeta__Sku Heading Text--subdued u-h6')
                if sku_container:
                    sku_span = sku_container.find('span', class_='ProductMeta__SkuNumber')
                    if sku_span and sku_span.get_text(strip=True):
                        sku_text = sku_span.get_text(strip=True)
                product_data['sku'] = sku_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping SKU: {e}")

            # ------- CATEGORY -------
            try:
                categories = []
                breadcrumb_container = soup.find('ol', class_='breadcrumbs__list')
                if breadcrumb_container:
                    a_tags = breadcrumb_container.find_all('a', class_='breadcrumbs__link')
                    for a_tag in a_tags:
                        text = a_tag.get_text(strip=True)
                        if text and text.lower() != 'home':
                            categories.append(text)
                product_data["category"] = categories
            except Exception as e:
                self.log_debug(f"Exception occurred while extracting categories from breadcrumbs: {e}")
                product_data["category"] = []

            # ------- VARIANTS -------
            try:
                variants = []
                select_tag = soup.find('select', {'id': 'option-0'})
                if select_tag:
                    options = select_tag.find_all('option')
                    for option in options:
                        size = option.text.strip()
                        available = not option.has_attr('disabled')
                        variants.append({
                            "size": size,
                            "availability": available
                        })
                product_data['variants'] = variants
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping size variants: {e}")
                product_data['variants'] = []


            # ------- IMAGES -------
            try:
                image_links = []
                media_divs = soup.find_all("div", class_="media")
                for media in media_divs:
                    image_href = media.get("href")
                    if image_href:
                        if image_href.startswith("//"):
                            image_href = "https:" + image_href
                        image_links.append(image_href)
                product_data["images"] = image_links
            except Exception as e:
                self.log_debug(f"Error while scraping images: {e}")
                product_data["images"] = []

            # ------- SHIPPING & RETURNS -------
            try:
                toggle_content = soup.find('div', class_='toggle-content', id='tab-shipping-amp-return-mobile')
                shipping_and_returns = ""
                if toggle_content:
                    paragraphs = toggle_content.find_all(['h3', 'p'])
                    content_lines = [tag.get_text(strip=True) for tag in paragraphs if tag.get_text(strip=True)]
                    shipping_and_returns = "\n".join(content_lines)
                product_data['raw_data']['shipping_and_return'] = shipping_and_returns
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping shipping and returns: {e}")
                product_data['raw_data']['shipping_and_return'] = ""

            # ------- DESCRIPTION -------
            try:
                description_text = ""
                desc_div = soup.find('div', class_='productView-desc halo-text-format')
                if desc_div:
                    parts = []
                    for p in desc_div.find_all('p'):
                        txt = p.get_text(separator=" ", strip=True)
                        if txt:
                            parts.append(txt)
                    for li in desc_div.find_all('li'):
                        txt = li.get_text(separator=" ", strip=True)
                        if txt:
                            parts.append(f"- {txt}")
                    description_text = "\n\n".join(parts)
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            # ------- PRICE -------
            try:
                def parse_price(text):
                    match = re.search(r'([\d,]+\.\d{2})', text)
                    return match.group(1).replace(',', '') if match else None

                price_container = soup.find("div", class_="productView-price")
                if price_container:
                    saved_tag = price_container.find("span", class_="price-item--saved")
                    if saved_tag:
                        sale_price_tag = price_container.find("span", class_="price-item--sale")
                        original_price_tag = price_container.find("s", class_="price-item--regular")
                        if sale_price_tag and original_price_tag:
                            product_data["currency"] = "Rs."
                            product_data["original_price"] = parse_price(original_price_tag.get_text())
                            product_data["sale_price"] = parse_price(sale_price_tag.get_text())
                    else:
                        original_price_tag = price_container.find("span", class_="price-item--regular")
                        if original_price_tag:
                            product_data["currency"] = "Rs."
                            product_data["original_price"] = parse_price(original_price_tag.get_text())
                            product_data["sale_price"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while extracting price: {e}")

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

                # Updated: Select <a> tags with class 'card-link'
                product_links = soup.select('a.card-link')

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

                # Pagination: look for next page link (adjust selector based on site)
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
