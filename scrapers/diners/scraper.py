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
from utils.LoggerConstants import Diner_Logger
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.parse import urljoin
import time



class DinnerScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://diners.com.pk/",
            logger_name=Diner_Logger,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "diners"
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
                'currency': "PKR",  # Default currency for Diners
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
                    title_tag = soup.select_one('h1.productView-title span')
                    product_data['title'] = title_tag.get_text(strip=True) if title_tag else None
                except Exception as e:
                    print(f"Error extracting product title: {e}")

                # --- SKU ---
                try:
                    sku_element = soup.select_one('div.productView-info-item span.productView-info-value')
                    product_data['sku'] = sku_element.get_text(strip=True) if sku_element else None
                except Exception as e:
                    print(f"Error extracting SKU: {e}")

                # --- Reviews ---
                review_data = {}
                try:
                    review_div = soup.find('div', class_='jdgm-prev-badge')
                    if review_div:
                        num_reviews = review_div.get('data-number-of-reviews', '0')
                        review_data['reviews'] = int(num_reviews)
                        stars_span = review_div.find('span', class_='jdgm-prev-badge__stars')
                        review_data['star_rating'] = float(stars_span.get('data-score', '0')) if stars_span else None
                    else:
                        review_data['reviews'] = 0
                        review_data['star_rating'] = None
                except Exception as e:
                    print(f"Error extracting review data: {e}")
                product_data['raw_data']['review_info'] = review_data

                # --- Product Type (Attributes) ---
                try:
                    info_items = soup.select('div.productView-info-item')
                    for item in info_items:
                        name = item.select_one('span.productView-info-name')
                        value = item.select_one('span.productView-info-value')
                        if name and value and 'Product Type' in name.get_text(strip=True):
                            product_data['attributes']['product_type'] = value.get_text(strip=True)
                            break
                except Exception as e:
                    print(f"Error extracting product type: {e}")

                # --- Price Extraction ---
                try:
                    price_container = soup.find("div", class_="productView-price")
                    if not price_container:
                        price_container = soup.find("div", class_="price")

                    if price_container:
                        original_price = None
                        sale_price = None

                        # Try to find "compare at" price
                        compare_price = price_container.find("s", class_="price-item--regular")
                        if compare_price:
                            compare_text = compare_price.get_text(strip=True)
                            if compare_text:
                                original_price = compare_text

                        # Try to find sale price
                        sale_span = price_container.find("span", class_="price-item--sale")
                        if sale_span:
                            sale_price = sale_span.get_text(strip=True)

                        # If no sale, fallback to regular
                        if not sale_price:
                            regular_span = price_container.find("span", class_="price-item--regular")
                            sale_price = regular_span.get_text(strip=True) if regular_span else None
                            original_price = sale_price

                        # Clean values
                        def clean_price(text):
                            return ''.join(ch for ch in text if ch.isdigit() or ch == '.').strip()

                        if original_price:
                            original_price = clean_price(original_price)
                        if sale_price:
                            sale_price = clean_price(sale_price)

                        # Apply logic
                        if original_price and sale_price and original_price == sale_price:
                            sale_price = None
                        if not original_price and sale_price:
                            original_price = sale_price
                            sale_price = None

                        product_data['original_price'] = original_price
                        product_data['sale_price'] = sale_price
                        product_data['currency'] = "PKR"
                except Exception as e:
                    print(f"Error extracting price: {e}")

                            # --- Images (scrape only one quality, prefer high-res) ---
                try:
                    product_data['images'] = []  # reset images just in case
                    
                    # Prefer images from the gallery (usually high-res)
                    image_divs = soup.select('div.media[data-fancybox="images"]')
                    if image_divs:
                        for div in image_divs:
                            href = div.get('href')
                            if href:
                                full_url = urljoin('https:', href)
                                if full_url not in product_data['images']:
                                    product_data['images'].append(full_url)
                    else:
                        # Fallback: use featured images (but only main one)
                        featured_img = soup.select_one('img[id^="product-featured-image-"]')
                        if featured_img:
                            src = featured_img.get('src')
                            if src:
                                full_url = urljoin('https:', src)
                                if full_url not in product_data['images']:
                                    product_data['images'].append(full_url)

                except Exception as e:
                    print(f"Error extracting image URLs: {e}")


                # --- Description ---
                try:
                    container = soup.select_one('div#tab-product-detail-mobile.toggle-content.show-mobile.is-active')
                    if container:
                        raw_html = container.decode_contents()
                        soup_inner = BeautifulSoup(raw_html, 'html.parser')
                        lines = []

                        for p in soup_inner.find_all('p'):
                            text = p.get_text(strip=True)
                            if text:
                                lines.append(text)

                        for li in soup_inner.find_all('li'):
                            text = li.get_text(strip=True)
                            if text:
                                lines.append(text)

                        product_data['description'] = '\n'.join(lines) if lines else None
                except Exception as e:
                    print(f"Error extracting description: {e}")

                # --- Sizes (Variants) ---
                try:
                    size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
                    if size_fieldset:
                        size_options = size_fieldset.find_all('input', {'type': 'radio'})
                        for option in size_options:
                            size = option.get('value', '').strip()
                            label = option.find_next_sibling('label')
                            is_available = not (label and 'soldout' in label.get('class', []))
                            product_data['variants'].append({
                                'size': size,
                                'availability': is_available
                            })
                except Exception as e:
                    print(f"Error extracting sizes: {e}")

            except Exception as e:
                self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

            return product_data




   
    async def scrape_products_links(self, url):
        all_product_links = []

        # Clean URL
        split_url = urlsplit(url)
        url = urlunsplit((split_url.scheme, split_url.netloc, split_url.path, split_url.query, ''))

        try:
            # --- First page ---
            self.log_info(f"Scraping page 1: {url}")
            response = await self.async_make_request(url)
            soup = BeautifulSoup(response.text, 'html.parser')

            # Get pagination info
            total_pages = 1
            pagination = soup.select_one(".pagination-wrapper.text-center")
            if pagination:
                try:
                    total_span = pagination.select_one('[data-total-end]')
                    total_end = int(total_span.text.strip()) if total_span else None

                    total_text = pagination.get_text(strip=True)
                    # Example: "Showing 1-50 of 74 total"
                    if "of" in total_text:
                        total_products = int(total_text.split("of")[-1].split("total")[0].strip())
                        if total_end:
                            total_pages = -(-total_products // total_end)  # ceiling division
                except Exception as e:
                    self.log_error(f"Error parsing pagination: {e}")

            # Collect products from page 1
            product_anchors = soup.select('a.card-link[href^="/products/"]')
            for anchor in product_anchors:
                href = anchor.get('href')
                if href:
                    product_url = urljoin(self.base_url, href)
                    if product_url not in all_product_links:
                        all_product_links.append(product_url)

            # --- Remaining pages ---
            for page in range(2, total_pages + 1):
                page_url = f"{url}?page={page}"
                self.log_info(f"Scraping page {page}: {page_url}")

                try:
                    response = await self.async_make_request(page_url)
                    soup = BeautifulSoup(response.text, 'html.parser')

                    product_anchors = soup.select('a.card-link[href^="/products/"]')
                    for anchor in product_anchors:
                        href = anchor.get('href')
                        if href:
                            product_url = urljoin(self.base_url, href)
                            if product_url not in all_product_links:
                                all_product_links.append(product_url)

                except Exception as e:
                    self.log_error(f"Error scraping page {page}: {e}")

        except Exception as e:
            self.log_error(f"Error scraping first page: {e}")

        self.log_info(f"Collected {len(all_product_links)} product link(s) across {total_pages} page(s).")
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
