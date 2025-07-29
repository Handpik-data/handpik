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
from utils.LoggerConstants import BEEJAYS_LOGGER
from urllib.parse import urljoin, urlparse
import time


class BeejaysScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://beejaysofficial.com/",
            logger_name=BEEJAYS_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "beejays"
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

            # Title
            try:
                product_title_tag = soup.find('h1', class_='ProductMeta__Title Heading u-h2')
                if product_title_tag and product_title_tag.get_text(strip=True):
                    product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")

            # Description from accordion
            try:
                description_text = ""
                accordion_content = soup.find('div', class_='accordion__content prose')
                if accordion_content:
                    p_tag = accordion_content.find('p')
                    if p_tag:
                        description_text = p_tag.get_text(separator=" ", strip=True)

                    li_tags = accordion_content.find_all('li')
                    bullet_points = [li.get_text(separator=" ", strip=True) for li in li_tags]

                    if bullet_points:
                        description_text += "\nBullet Points:\n" + "\n".join(f"- {point}" for point in bullet_points)

                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")

            # Price scraping with dot removal logic
            try:
                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price = re.sub(r'[^\d.]', '', text).lstrip('.')  # <- Clean leading dot
                    return price, currency

                price_div = soup.find('div', class_='ProductMeta__PriceList Heading')
                price_spans = price_div.find_all('span') if price_div else []

                if price_spans:
                    prices = []
                    for span in price_spans:
                        price_text = span.get_text(strip=True)
                        price, currency = extract_price(price_text)
                        prices.append((price, currency))

                    if len(prices) >= 2:
                        product_data['original_price'] = prices[0][0]
                        product_data['sale_price'] = prices[1][0]
                        product_data['currency'] = prices[0][1] or prices[1][1]
                    elif len(prices) == 1:
                        product_data['original_price'] = prices[0][0]
                        product_data['sale_price'] = None
                        product_data['currency'] = prices[0][1]
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping price: {e}")

            # Variants / Sizes
            try:
                variants = []
                sizes = []
                size_div = soup.find('div', class_='Popover__ValueList')
                if size_div:
                    buttons = size_div.find_all('button', class_='Popover__Value')
                    for button in buttons:
                        size_text = button.get_text(strip=True)
                        availability = True  # adjust logic if needed
                        sizes.append({'size': size_text, 'availability': availability})

                for size in sizes:
                    variants.append({
                        'size': size['size'],
                        'availability': 'true' if size['availability'] else 'false'
                    })

                product_data['variants'] = variants
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes/variants: {e}")

            # Images
            try:
                product_images = []
                img_tags = soup.find_all('img', attrs={'data-original-src': True})
                for img_tag in img_tags:
                    src = img_tag.get('data-original-src')
                    if src:
                        full_url = src if src.startswith('http') else 'https:' + src
                        product_images.append(full_url)

                product_images = list(set(product_images))
                product_data['images'] = product_images

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping images: {e}")

            # RTE Description (Overwrites earlier if exists)
            try:
                description_text = ""
                rte_div = soup.find('div', class_='Rte')
                if rte_div:
                    desc_parts = []
                    p_tags = rte_div.find_all('p')
                    for p in p_tags:
                        text = p.get_text(separator=" ", strip=True)
                        if text:
                            desc_parts.append(text)

                    ul_tags = rte_div.find_all('ul')
                    for ul in ul_tags:
                        li_items = ul.find_all('li')
                        for li in li_items:
                            strong_tag = li.find('strong')
                            text = strong_tag.get_text(separator=" ", strip=True) if strong_tag else li.get_text(separator=" ", strip=True)
                            if text:
                                desc_parts.append(text)

                    description_text = "\n".join(desc_parts).strip()
                    product_data['description'] = description_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping RTE description: {e}")

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data



    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        visited_pages = set()
        current_url = url

        while current_url and current_url not in visited_pages:
            try:
                visited_pages.add(current_url)
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Extract product links
                product_links = soup.select('a.ProductItem__ImageWrapper')
                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Find next page via rel="next"
                next_page_tag = soup.select_one('a[rel="next"]')
                if next_page_tag:
                    next_href = next_page_tag.get('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                    else:
                        self.log_info("No href found in next page link. Stopping.")
                        break
                else:
                    self.log_info("No next page found. Finished scraping all pages.")
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
