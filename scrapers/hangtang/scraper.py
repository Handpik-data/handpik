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
from utils.LoggerConstants import HANGTANG_LOGGER
from urllib.parse import urljoin, urlparse
import time


class HangtanScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://hangten.com.pk/",
            logger_name=HANGTANG_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "hangtang"
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

            try:
                product_title_tag = soup.find('h1', class_='product-title')
                if product_title_tag:
                    # Get text from <span> inside h1 if exists, else get h1 text
                    span_tag = product_title_tag.find('span')
                    if span_tag and span_tag.get_text(strip=True):
                        product_data["title"] = span_tag.get_text(strip=True)
                    else:
                        product_data["title"] = product_title_tag.get_text(strip=True)
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None



            try:
                breadcrumbs = []
                breadcrumb_container = soup.find('div', class_='breadcrumb')
                if breadcrumb_container:
                    # Find all <a> tags inside breadcrumb
                    a_tags = breadcrumb_container.find_all('a')
                    for a_tag in a_tags:
                        crumb = a_tag.get_text(strip=True)
                        if crumb:
                            breadcrumbs.append(crumb)
                    
                    # Find all <span> tags directly under breadcrumb (excluding arrows)
                    span_tags = breadcrumb_container.find_all('span', recursive=False)
                    for span_tag in span_tags:
                        # Check if span has an <a> inside it
                        inner_a = span_tag.find('a')
                        if inner_a:
                            crumb = inner_a.get_text(strip=True)
                            if crumb:
                                breadcrumbs.append(crumb)
                        else:
                            # If span contains direct text and is not an arrow
                            if 'arrow' not in span_tag.get('class', []):
                                crumb = span_tag.get_text(strip=True)
                                if crumb:
                                    breadcrumbs.append(crumb)

                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []

  
           



            try:
                # Initialize variables
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None

                def extract_price(text):
                    text = text.replace("From", "").strip()
                    # Extract currency (non-digit characters at start)
                    currency_match = re.match(r'^([^\d]+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None

                    # Extract numeric price: first digit onwards, remove commas
                    price_match = re.search(r'(\d[\d,\.]*)', text)
                    price = price_match.group(1).replace(",", "") if price_match else None

                    return price, currency

                price_container = soup.find('div', class_='prices')
                if price_container:
                    # Extract original price from <span class="compare-price">
                    compare_span = price_container.find('span', class_='compare-price')
                    if compare_span:
                        original_text = compare_span.get_text(strip=True)
                        original_price, currency = extract_price(original_text)
                        product_data['original_price'] = original_price
                        product_data['currency'] = currency

                    # Extract sale price from <span class="price on-sale">
                    sale_span = price_container.find('span', class_='price on-sale')
                    if sale_span:
                        sale_text = sale_span.get_text(strip=True)
                        sale_price, currency = extract_price(sale_text)
                        product_data['sale_price'] = sale_price
                        if not product_data['currency']:
                            product_data['currency'] = currency

                    # If sale price missing from span, fallback to hidden input field
                    if not product_data['sale_price']:
                        hidden_price_input = price_container.find('input', id='product_regular_price')
                        if hidden_price_input:
                            hidden_price_value = hidden_price_input.get('value')
                            if hidden_price_value:
                                # Convert '74700' to '747.00' by dividing by 100 if applicable
                                try:
                                    price_int = int(hidden_price_value)
                                    price_float = price_int / 100
                                    product_data['sale_price'] = f"{price_float:.2f}"
                                except:
                                    product_data['sale_price'] = hidden_price_value

            except Exception as e:
                print(f"Error extracting price data: {e}")
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None




            try:
                categories = []

                # Find the <div> with class 'breadcrumb'
                breadcrumb_div = soup.find('div', class_='breadcrumb')
                if breadcrumb_div:
                    # Find all direct children tags within breadcrumb_div
                    for tag in breadcrumb_div.find_all(['a', 'span'], recursive=False):
                        # Skip 'Home' link
                        if tag.name == 'a' and 'Home' in tag.get_text(strip=True):
                            continue

                        # If <a> tag and not 'Home'
                        if tag.name == 'a':
                            category_text = tag.get_text(strip=True)
                            if category_text:
                                categories.append(category_text)

                        # If <span> tag
                        elif tag.name == 'span':
                            # Check if this <span> has a nested <a>
                            nested_a = tag.find('a')
                            if nested_a:
                                category_text = nested_a.get_text(strip=True)
                                if category_text:
                                    categories.append(category_text)
                            else:
                                # Otherwise, get direct text from <span>
                                category_text = tag.get_text(strip=True)
                                if category_text:
                                    categories.append(category_text)

                product_data["category"] = categories

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping categories from breadcrumbs: {e}")
                product_data["category"] = []


            try:
                    variants = []

                    # Find all color swatches
                    color_swatch = soup.find('div', class_='swatch', attrs={'data-option-index': '0'})
                    colors = []
                    if color_swatch:
                        color_elements = color_swatch.find_all('div', class_='swatch-element')
                        for color_elem in color_elements:
                            color_name = color_elem.get('data-value', '').strip()
                            color_availability = 'false' if 'soldout' in color_elem.get('class', []) else 'true'
                            colors.append({
                                'color': color_name,
                                'availability': color_availability
                            })

                    # Find all size swatches
                    size_swatch = soup.find('div', class_='swatch', attrs={'data-option-index': '1'})
                    sizes = []
                    if size_swatch:
                        size_elements = size_swatch.find_all('div', class_='swatch-element')
                        for size_elem in size_elements:
                            size_name = size_elem.get('data-value', '').strip()
                            size_availability = 'false' if 'soldout' in size_elem.get('class', []) else 'true'
                            sizes.append({
                                'size': size_name,
                                'availability': size_availability
                            })

                    # Combine colors and sizes into variants
                    for color in colors:
                        for size in sizes:
                            variant = {
                                'color': color['color'],
                                'size': size['size'],
                                'availability': 'true' if color['availability'] == 'true' and size['availability'] == 'true' else 'false'
                            }
                            variants.append(variant)

                    product_data['variants'] = variants

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping variants: {e}")
                product_data['variants'] = []




        
            try:
                product_images = []

                # Find all <img> tags with 'src' attribute containing '/products/'
                img_tags = soup.find_all('img')

                for img_tag in img_tags:
                    src_img_url = img_tag.get('src')
                    if src_img_url and '/products/' in src_img_url:
                        # Prepend 'https:' if URL starts with '//'
                        if src_img_url.startswith('//'):
                            src_img_url = 'https:' + src_img_url
                        elif src_img_url.startswith('/'):
                            src_img_url = 'https://hangten.com.pk' + src_img_url

                        # Optional: Only include URLs with 'compact' or highest quality identifier
                        if 'compact' in src_img_url or 'large' in src_img_url or 'master' in src_img_url:
                            product_images.append(src_img_url)

                # Remove duplicates while preserving order
                seen = set()
                unique_images = []
                for img in product_images:
                    if img not in seen:
                        unique_images.append(img)
                        seen.add(img)

                product_data['images'] = unique_images

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

           

            try:
                description_text = ""

                # Find the <div> with id 'collapse-tab1'
                desc_div = soup.find('div', id='collapse-tab1')
                if desc_div:
                    # Find the first inner <div> containing the description text
                    inner_div = desc_div.find('div')
                    if inner_div:
                        # Extract text including paragraphs and list items, separated by spaces
                        description_text = inner_div.get_text(separator=" ", strip=True)

                product_data['description'] = description_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            try:
                # Initialize dictionaries to hold policies
                return_policy = ""
                care_instructions = ""
                delivery_info = ""

                # --- Return & Exchange Policy ---
                return_div = soup.find('div', id='collapse-tab3', class_='tab-content')
                if return_div:
                    inner_div = return_div.find('div')
                    if inner_div:
                        return_text = inner_div.get_text(separator=" ", strip=True)
                        return_policy = return_text

                # --- Product Care Instructions ---
                care_div = soup.find('div', id='collapse-tab4', class_='tab-content')
                if care_div:
                    inner_div = care_div.find('div')
                    if inner_div:
                        care_text = inner_div.get_text(separator=" ", strip=True)
                        care_instructions = care_text

                # --- Delivery & Shipping ---
                delivery_div = soup.find('div', id='collapse-tab5', class_='tab-content')
                if delivery_div:
                    inner_div = delivery_div.find('div')
                    if inner_div:
                        delivery_text = inner_div.get_text(separator=" ", strip=True)
                        delivery_info = delivery_text

                # Save in raw_data
                product_data['raw_data']['return_policy'] = return_policy
                product_data['raw_data']['care_instructions'] = care_instructions
                product_data['raw_data']['delivery_info'] = delivery_info

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping policies: {e}")
                product_data['raw_data']['return_policy'] = ""
                product_data['raw_data']['care_instructions'] = ""
                product_data['raw_data']['delivery_info'] = ""






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

                # Select <a> tags with class 'product-grid-image adaptive_height'
                product_links = soup.select('a.product-grid-image.adaptive_height')

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
