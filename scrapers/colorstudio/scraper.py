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
from utils.LoggerConstants import COLORSTUDIOPRO_LOGGER
from urllib.parse import urljoin, urlparse
import time


class ColoStudioScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://www.colorstudiopro.com/",
            logger_name=COLORSTUDIOPRO_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "colorstudiopro"
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
                title_tag = soup.find('h1', class_='product-detail__title heading-letter-spacing fs-26 mt-0 mb-10 skeleton-loading')
                product_data["title"] = title_tag.get_text(strip=True) if title_tag else None
            except Exception as e:
                self.log_debug(f"Error scraping title: {e}")

            # Breadcrumbs / Category
            try:
                breadcrumbs = []
                breadcrumb_ul = soup.find('ul', class_='breadcrumb-list')
                if breadcrumb_ul:
                    li_tags = breadcrumb_ul.find_all('li', class_='breadcrumb-item')
                    for li in li_tags:
                        span_tag = li.find('span')
                        a_tag = li.find('a')
                        text = span_tag.get_text(strip=True) if span_tag else a_tag.get_text(strip=True) if a_tag else None
                        if text and text.lower() != 'home':
                            breadcrumbs.append(text)
                product_data['attributes']['breadcrumbs'] = breadcrumbs
                product_data['category'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Error scraping breadcrumbs: {e}")

          
            # Price
            try:
                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price = re.sub(r'[^\d.]', '', text)
                    if price.startswith('.'):
                        price = price[1:]
                    return price, currency

                price_container = soup.find('div', class_='product-detail__price')
                if price_container:
                    price_divs = price_container.find_all('div', class_='price-regular')

                    if len(price_divs) >= 1:
                        sale_span = price_divs[0].find('span', class_='price')
                        if sale_span:
                            sale_price, currency = extract_price(sale_span.get_text(strip=True))
                            product_data['sale_price'] = sale_price
                            product_data['currency'] = currency

                    if len(price_divs) >= 2:
                        original_s_tag = price_divs[1].find('s', class_='price-item')
                        if original_s_tag:
                            original_price, currency = extract_price(original_s_tag.get_text(strip=True))
                            product_data['original_price'] = original_price
                            if not product_data['currency']:
                                product_data['currency'] = currency
            except Exception as e:
                self.log_debug(f"Error extracting price data: {e}")

                    # Promotions
            try:
                promotions = []
                promo_divs = soup.find_all('div', class_='rich__text-m0 flex-1 align-center text-left')
                for div in promo_divs:
                    p_tag = div.find('p')
                    if p_tag:
                        text = p_tag.get_text(separator=" ", strip=True)
                        if text:
                            promotions.append(text)
                product_data['raw_data']['promotions'] = promotions
            except Exception as e:
                self.log_debug(f"Error scraping promotions: {e}")
                product_data['raw_data']['promotions'] = []

            # Return policy (Plain Text)
            try:
                refund_div = soup.find("div", class_="overflow-hidden collapsible-content")
                return_policy_text = ""
                if refund_div:
                    inner_div = refund_div.find("div", class_="collapsible-content_inner")
                    if inner_div:
                        return_policy_text = inner_div.get_text(separator=" ", strip=True)
                product_data['raw_data']['return_policy'] = return_policy_text
            except Exception as e:
                self.log_debug(f"Error scraping return policy: {e}")
                product_data['raw_data']['return_policy'] = ""


            # Product Images (Only one quality per image)
            try:
                image_set = set()
                divs = soup.find_all('div', class_='t4s_ratio t4s-product__media is-pswp-disable')
                for div in divs:
                    img_tags = div.find_all('img')
                    for img in img_tags:
                        img_url = None
                        for key in ['data-master', 'data-srcset', 'data-src', 'src']:
                            val = img.get(key)
                            if val:
                                if key == 'data-srcset':
                                    parts = val.strip().split(',')
                                    if parts:
                                        val = parts[-1].split(' ')[0]
                                img_url = val
                                break
                        if img_url:
                            img_url = 'https:' + img_url if img_url.startswith('//') else img_url
                            img_url = img_url.split('?')[0]  # remove query params
                            image_set.add(img_url)
                product_data['images'] = list(image_set)
            except Exception as e:
                self.log_debug(f"Error scraping product images: {e}")

            # Description
            try:
                desc_div = soup.find('div', class_='product-description')
                description_text = ""
                if desc_div:
                    description_text = " ".join(p.get_text(separator=" ", strip=True) for p in desc_div.find_all('p') if p.get_text(strip=True))
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Error scraping description: {e}")

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

                # Select <a> tags with class 'product__media'
                product_links = soup.select('a.product__media')

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

                # Pagination: look for next page link (adjust selector if site uses different pagination)
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
