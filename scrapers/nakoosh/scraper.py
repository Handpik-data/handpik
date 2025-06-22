import os
import re
import json
import asyncio
from statistics import variance
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import NAKOOSH_LOGGER
from urllib.parse import urljoin
import time


class nakoosh_Scrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://nakoosh.com/",
            logger_name=NAKOOSH_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "nakoosh"
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

            # Product Title
            try:
                title_tag = soup.select_one('h1.product-title span')
                if title_tag:
                    product_data['title'] = title_tag.get_text(strip=True)
                else:
                    product_data['title'] = None
            except Exception as e:
                product_data['title'] = None
                print(f"Error extracting product title: {e}")

            # SKU
            try:
                sku_element = soup.select_one('div.sku-product > span')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
                else:
                    product_data['sku'] = None
            except Exception as e:
                product_data['sku'] = None
                print(f"Error extracting SKU: {e}")

            # Extract category from breadcrumb
            try:
                breadcrumb_nav = soup.select('nav.breadcrumb a')
                if breadcrumb_nav and len(breadcrumb_nav) >= 2:
                    product_data['category'] = breadcrumb_nav[-1].get_text(strip=True)
                else:
                    product_data['category'] = None
            except Exception as e:
                product_data['category'] = None
                print(f"Error extracting category from breadcrumb: {e}")

            # Scrape the brand/shop name
            try:
                vendor_div = soup.select_one('div.vendor-product')
                brand_name = None
                if vendor_div:
                    brand_link = vendor_div.select_one('span a')
                    if brand_link:
                        brand_name = brand_link.get_text(strip=True)
                product_data['brand'] = brand_name
            except Exception as e:
                product_data['brand'] = None
                print(f"Error extracting brand name: {e}")

            # Prices
            try:
                price_div = soup.find("div", class_="prices")
                if price_div:
                    # Try to extract original price
                    original_price_tag = price_div.select_one("span.compare-price span.money")
                    if original_price_tag:
                        price_text = original_price_tag.get_text(strip=True).replace("Rs.", "").replace(",", "")
                        try:
                            product_data["original_price"] = float(price_text)
                        except ValueError:
                            product_data["original_price"] = None

                    # Try to extract sale price
                    sale_price_tag = price_div.select_one("span.price.on-sale span.money")
                    if sale_price_tag:
                        price_text = sale_price_tag.get_text(strip=True).replace("Rs.", "").replace(",", "")
                        try:
                            product_data["sale_price"] = float(price_text)
                        except ValueError:
                            product_data["sale_price"] = None

                    # Fallback: single price
                    if "original_price" not in product_data and "sale_price" not in product_data:
                        single_price_tag = price_div.select_one("span.money")
                        if single_price_tag:
                            price_text = single_price_tag.get_text(strip=True).replace("Rs.", "").replace(",", "")
                            try:
                                product_data["original_price"] = float(price_text)
                                product_data["sale_price"] = None
                            except ValueError:
                                product_data["original_price"] = None
                                product_data["sale_price"] = None

                    elif "original_price" not in product_data and "sale_price" in product_data:
                        product_data["original_price"] = product_data["sale_price"]
                        product_data["sale_price"] = None

                    product_data["currency"] = "PKR"
                else:
                    product_data["original_price"] = None
                    product_data["sale_price"] = None
                    product_data["currency"] = "PKR"
            except Exception as e:
                product_data["original_price"] = None
                product_data["sale_price"] = None
                product_data["currency"] = "PKR"
                print(f"Error extracting prices: {e}")

            # Initialize attributes if not already
            product_data['attributes'] = product_data.get('attributes', {})

            try:
                # Find the breadcrumb container
                breadcrumb_div = soup.select_one('div.breadcrumb')
                breadcrumbs = []

                if breadcrumb_div:
                    # Get all <a> inside breadcrumb
                    links = breadcrumb_div.find_all('a')
                    for a in links:
                        text = a.get_text(strip=True)
                        if text:
                            breadcrumbs.append(text)

                    # Get all final <span> elements without <a> or <i>
                    plain_spans = breadcrumb_div.find_all('span')
                    for span in plain_spans:
                        if not span.find('a') and not span.find('i'):
                            text = span.get_text(strip=True)
                            if text:
                                breadcrumbs.append(text)

                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                product_data['attributes']['breadcrumbs'] = []
                print(f"Error extracting breadcrumbs: {e}")

            # Description (moved outside the image loop)
            try:
                description_div = soup.select_one('div.short-description')
                if description_div:
                    description_text = description_div.get_text(separator='\n', strip=True).replace('\xa0', ' ')
                    product_data['description'] = description_text
                else:
                    product_data['description'] = None
            except Exception as e:
                product_data['description'] = None

            # Images (from product-single__media divs using data-image attribute)
            try:
                media_divs = soup.find_all('div', class_='product-single__media')
                for media_div in media_divs:
                    a_tag = media_div.find('a', attrs={'data-image': True})
                    if a_tag:
                        image_url = a_tag['data-image']
                        if image_url.startswith('//'):
                            image_url = 'https:' + image_url
                        full_url = urljoin(self.base_url, image_url)
                        if full_url not in product_data['images']:
                            product_data['images'].append(full_url)
            except Exception as e:
                print(f"Error extracting images: {e}")

            # Variants / Sizes with availability as boolean
            try:
                size_elements = soup.select("div.swatch-element")
                variants = []

                for element in size_elements:
                    size = element.get("data-value", "").strip()
                    class_list = element.get("class", [])

                    # Check availability logic
                    is_available = "available" in class_list

                    if size:
                        variants.append({
                            "size": size,
                            "availability": str(is_available).lower()
                        })

                product_data['variants'] = variants or None
            except Exception as e:
                product_data['variants'] = None
                print(f"Error extracting variants: {e}")

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data


    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(current_url)
     
                soup = BeautifulSoup(response.text, 'html.parser')

                # Find all <a> tags with specific class and href pattern
                link_tags = soup.select('a.product-grid-image[href*="/products/"]')

                if not link_tags:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                initial_count = len(all_product_links)

                for tag in link_tags:
                    href = tag.get("href")
                    if href:
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        if product_url not in all_product_links:
                            self.log_info(f"Found product link: {product_url}")
                        all_product_links.add(product_url)

                if len(all_product_links) == initial_count:
                    self.log_info("No new products found. Stopping.")
                    break

                page_number += 1
                if "?" not in url:
                    current_url = f"{url}?page={page_number}"
                else:
                    current_url = f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        self.log_info(f"Collected {len(all_product_links)} unique product links.")
        
        # ✅ Print all collected product links
        print("\nScraped Product Links:")
        for link in all_product_links:
            print(link)
        
        return list(all_product_links)



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
