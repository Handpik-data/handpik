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
from utils.LoggerConstants import EDENROBE_LOGGER
from urllib.parse import urljoin, urlparse
import time


class EdenRobeScrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://edenrobe.com/",
            logger_name=EDENROBE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Edenrobe"
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
                # Find <h1> with class 'product-title' inside 'product-title-container'
                product_title_container = soup.find('div', class_='product-title-container')
                if product_title_container:
                    product_title_tag = product_title_container.find('h1', class_='product-title')
                    if product_title_tag:
                        product_data["title"] = product_title_tag.get_text(strip=True)
                    else:
                        product_data["title"] = None
                else:
                    product_data["title"] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None


            try:
                # Find <div> with class 'barcodecss'
                barcode_div = soup.find('div', class_='barcodecss')
                if barcode_div:
                    # Extract the full text content
                    full_text = barcode_div.get_text(strip=True)
                    
                    # Remove 'Article No:' label to keep only the SKU
                    sku = full_text.replace('Article No:', '').strip()
                    
                    product_data['sku'] = sku
                else:
                    product_data['sku'] = None

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping SKU: {e}")
                product_data['sku'] = None



            try:
                breadcrumbs = []

                # Find the <nav> with class 'breadcrumbs'
                breadcrumb_nav = soup.find('nav', class_='breadcrumbs')
                if breadcrumb_nav:
                    # Find all <a> tags inside breadcrumbs
                    a_tags = breadcrumb_nav.find_all('a')
                    for a_tag in a_tags:
                        crumb = a_tag.get_text(strip=True)
                        if crumb:
                            breadcrumbs.append(crumb)

                    # Extract any direct text nodes (e.g. the product title text after <i>)
                    # Use .stripped_strings to iterate over all text excluding tags like <i>
                    for string in breadcrumb_nav.stripped_strings:
                        if string != '/':  # skip the '/' separator
                            if string not in breadcrumbs:  # avoid duplication if already in <a> tags
                                breadcrumbs.append(string)

                product_data['attributes']['breadcrumbs'] = breadcrumbs

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []

            try:
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None

                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^([^\d]+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price_match = re.search(r'(\d[\d,\.]*)', text)
                    price = price_match.group(1).replace(",", "") if price_match else None
                    return price, currency

                price_container = soup.find('span', class_='price')
                if price_container:
                    # ✅ Extract original price from <del> within compare-price amount span
                    compare_span = price_container.find('span', class_='compare-price amount')
                    if compare_span:
                        del_tag = compare_span.find('del')
                        if del_tag:
                            original_text = del_tag.get_text(strip=True)
                            original_price, currency = extract_price(original_text)
                            product_data['original_price'] = original_price
                            product_data['currency'] = currency

                    # ✅ Extract sale price from <span class="price on-sale amount">
                    sale_span = price_container.find('span', class_='price on-sale amount')
                    if sale_span:
                        sale_text = sale_span.get_text(strip=True)
                        sale_price, currency = extract_price(sale_text)
                        product_data['sale_price'] = sale_price
                        if not product_data['currency']:
                            product_data['currency'] = currency

                    # ✅ Fallback: if sale price missing, check hidden input field
                    if not product_data['sale_price']:
                        hidden_price_input = price_container.find('input', id='product_regular_price')
                        if hidden_price_input:
                            hidden_price_value = hidden_price_input.get('value')
                            if hidden_price_value:
                                try:
                                    price_int = int(hidden_price_value)
                                    price_float = price_int / 100
                                    product_data['sale_price'] = f"{price_float:.2f}"
                                    if not product_data['currency']:
                                        product_data['currency'] = "PKR"
                                except:
                                    product_data['sale_price'] = hidden_price_value

            except Exception as e:
                self.log_debug(f"Error extracting price data: {e}")
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['currency'] = None


            try:
                categories = []
                breadcrumb_nav = soup.find('nav', class_='breadcrumbs')
                if breadcrumb_nav:
                    # Extract all <a> tags excluding Home
                    a_tags = breadcrumb_nav.find_all('a')
                    for a in a_tags:
                        text = a.get_text(strip=True)
                        if text and text != "Home":
                            categories.append(text)
                    
                    # Extract remaining text nodes (e.g. final product name)
                    # Loop through contents to include direct text not inside tags
                    for content in breadcrumb_nav.contents:
                        if isinstance(content, str):
                            text = content.strip()
                            if text and text != "/" and text != "Home":
                                categories.append(text)
                        elif content.name == 'i':
                            continue
                        else:
                            inner_text = content.get_text(strip=True)
                            if inner_text and inner_text != "/" and inner_text != "Home":
                                categories.append(inner_text)

                product_data["category"] = categories

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping categories from breadcrumbs: {e}")
                product_data["category"] = []

   

            try:
                product_images = []

                # Find all specific <div> containers for product images
                image_divs = soup.find_all('div', class_='product-single__media product-single__media-image aspect-ratio aspect-ratio--adapt')
                for div in image_divs:
                    img_tag = div.find('img')
                    if img_tag:
                        # Prefer data-srcset for higher quality images
                        data_srcset = img_tag.get('data-srcset')
                        if data_srcset:
                            # Split by comma, extract highest resolution image
                            srcset_items = [item.strip() for item in data_srcset.split(',')]
                            if srcset_items:
                                last_item = srcset_items[-1]
                                parts = last_item.split(' ')
                                if parts:
                                    src_img_url = parts[0]
                        else:
                            # Fallback to src attribute
                            src_img_url = img_tag.get('src')

                        # Clean up URL
                        if src_img_url:
                            if src_img_url.startswith('//'):
                                src_img_url = 'https:' + src_img_url
                            elif src_img_url.startswith('/'):
                                src_img_url = 'https://edenrobe.com' + src_img_url

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
                sizes_status = []

                # ✅ Extract color first
                color_name = None
                color_label = soup.find('label', attrs={'for': lambda x: x and 'main-product-2-' in x})
                if color_label:
                    span = color_label.find('span')
                    if span:
                        color_name = span.get_text(strip=True)

                # ✅ Then extract sizes from <select> options
                select_tag = soup.find('select', id=lambda x: x and 'Variants' in x)
                if select_tag:
                    options = select_tag.find_all('option')
                    for option in options:
                        size_text = option.get_text(strip=True)
                        is_disabled = option.has_attr('disabled')
                        status = not is_disabled  # True = Available, False = Sold Out

                        sizes_status.append({
                            'size': size_text.split('/')[0].strip(),  # Extract size before '/'
                            'color': color_name,
                            'availability': status
                        })

                # Save in product_data['variants']
                product_data['variants'] = sizes_status

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes and colors: {e}")
                product_data['variants'] = []



            try:
                description_text = ""

                # Find the div with class 'product-short-description rte'
                desc_div = soup.find('div', class_='product-short-description rte')
                if desc_div:
                    # Get all <li> items inside it
                    li_items = desc_div.find_all('li')
                    description_lines = []
                    for li in li_items:
                        line = li.get_text(strip=True)
                        if line:
                            description_lines.append(line)
                    
                    # Join them with commas or keep as separate lines
                    description_text = ", ".join(description_lines)
                
                product_data['description'] = description_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""

            try:
                disclaimer_text = ""

                # Find <p> with class 'product--text style_vendor'
                disclaimer_p = soup.find('p', class_='product--text style_vendor')
                if disclaimer_p:
                    disclaimer_text = disclaimer_p.get_text(separator=" ", strip=True)

                # Save in product_data['raw_data']
                product_data['raw_data']['disclaimer'] = disclaimer_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping disclaimer: {e}")
                product_data['raw_data']['disclaimer'] = ""



           

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

                # Updated selector for <a> tags with class 'product-featured-image-link'
                product_links = soup.select('a.product-featured-image-link')

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
