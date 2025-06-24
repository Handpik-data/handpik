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
    def __init__(self, proxies=None, request_delay=1):
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

            # Product title
            try:
                title_tag = soup.select_one('h1.productView-title span')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
                else:
                    product_data['title'] = None
            except Exception as e:
                product_data['title'] = None
                print(f"Error extracting product title: {e}")

            # SKU
            try:
                sku_element = soup.select_one('div.productView-info-item span.productView-info-value')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
                else:
                    product_data['sku'] = None
            except Exception as e:
                product_data['sku'] = None
                print(f"Error extracting SKU: {e}")

            # Reviews and rating
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
                review_data['reviews'] = 0
                review_data['star_rating'] = None
                print(f"Error extracting review data: {e}")

            # Store in raw_data
            product_data['raw_data']['review_info'] = review_data

            # Product Type
            try:
                product_type = None
                info_items = soup.select('div.productView-info-item')
                for item in info_items:
                    name = item.select_one('span.productView-info-name')
                    value = item.select_one('span.productView-info-value')
                    if name and value and 'Product Type' in name.get_text(strip=True):
                        product_type = value.get_text(strip=True)
                        break
                product_data['category'] = product_type
            except Exception as e:
                product_data['category'] = None
                print(f"Error extracting product type: {e}")

                    # ----- Price Extraction (Updated for provided HTML structure) -----
            try:
                price_div = soup.find('div', class_='price price--medium price--on-sale')

                if price_div:
                    original_price_tag = price_div.select_one('s.price-item--regular')
                    sale_price_tag = price_div.select_one('span.price-item--sale')

                    def extract_price(text):
                        text = text.replace("From", "").strip()
                        currency_match = re.match(r'^(\D+)', text)
                        currency = currency_match.group(1).strip() if currency_match else None
                        price = re.sub(r'[^\d.]', '', text)
                        return price, currency

                    if original_price_tag and sale_price_tag:
                        original, currency = extract_price(original_price_tag.get_text(strip=True))
                        sale, _ = extract_price(sale_price_tag.get_text(strip=True))
                        product_data["original_price"] = original
                        product_data["sale_price"] = sale
                        product_data["currency"] = currency

                    elif sale_price_tag:
                        sale, currency = extract_price(sale_price_tag.get_text(strip=True))
                        product_data["original_price"] = sale
                        product_data["sale_price"] = None
                        product_data["currency"] = currency

                    else:
                        product_data["original_price"] = None
                        product_data["sale_price"] = None
                        product_data["currency"] = None
                else:
                    product_data["original_price"] = None
                    product_data["sale_price"] = None
                    product_data["currency"] = None

            except Exception as e:
                product_data["original_price"] = None
                product_data["sale_price"] = None
                product_data["currency"] = None
                print(f"Error extracting price data: {e}")
            # Images
            try:
                image_divs = soup.select('div.media[data-fancybox="images"]')
                image_imgs = soup.select('img[id^="product-featured-image-"]')

                for div in image_divs:
                    href = div.get('href')
                    if href:
                        full_url = urljoin('https:', href)
                        if full_url not in product_data['images']:
                            product_data['images'].append(full_url)

                for img in image_imgs:
                    src = img.get('src') or img.get('srcset')
                    if src:
                        full_url = urljoin('https:', src)
                        if full_url not in product_data['images']:
                            product_data['images'].append(full_url)
            except Exception as e:
                print(f"Error extracting image URLs: {e}")

          # Description
            try:
                description_container = soup.select_one('div#tab-product-detail-mobile.toggle-content.show-mobile.is-active')
                if description_container:
                    raw_html = description_container.decode_contents()
                    soup_inner = BeautifulSoup(raw_html, 'html.parser')

                    lines = []

                    # Extract warning/note text from the first <div> (if any)
                    warning_div = soup_inner.find('div')
                    if warning_div:
                        lines.append(warning_div.get_text(strip=True))

                    # Extract details from <ul><li>...
                    li_items = soup_inner.find_all('li')
                    for li in li_items:
                        lines.append(li.get_text(strip=True))

                    product_data['description'] = '\n'.join(lines) if lines else None
                else:
                    product_data['description'] = None
            except Exception as e:
                product_data['description'] = None
                print(f"Error extracting description: {e}")
      

            # Sizes (✔️ Updated to store in "variants" with boolean "availability")
            try:
                size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
                if size_fieldset:
                    size_options = size_fieldset.find_all('input', {'type': 'radio'})
                    variants_list = []

                    for option in size_options:
                        size = option.get('value', '').strip()
                        label = option.find_next_sibling('label')
                        is_available = not (label and 'soldout' in label.get('class', []))

                        variants_list.append({
                            'size': size,
                            'availability': is_available  # Boolean: True or False
                        })

                    product_data['variants'] = variants_list
                else:
                    product_data['variants'] = []
                    self.log_debug("Size selection fieldset not found on the page.")
            except Exception as e:
                product_data['variants'] = []
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
                self.log_info(f"Scraping page 1: {url}")
                response = await self.async_make_request(url)

                soup = BeautifulSoup(response.text, 'html.parser')

                # Match anchor tags with class 'card-link' and href starting with /products/
                product_anchors = soup.select('a.card-link[href^="/products/"]')

                if not product_anchors:
                    self.log_info("No product links found on the first page.")
                    return []

                for anchor in product_anchors:
                    href = anchor.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

            except Exception as e:
                self.log_error(f"Error scraping page: {e}")

            self.log_info(f"Collected {len(all_product_links)} product link(s).")
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
