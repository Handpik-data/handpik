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
from utils.LoggerConstants import ETHINIC_LOGGER
from urllib.parse import urljoin
from urllib.parse import urljoin, urlparse, urlunparse, parse_qs
import time


class EthinicScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://pk.ethnc.com/",
            logger_name=ETHINIC_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "ethinic"
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
        try:
            response = requests.get(product_link)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
        'title': None,
        'store_name':'ethinic',
        'brand':None,
        'category':None,
        'avaliblity':None,
        'sku': None,
        'original_price': None,
        'sale_price': None,
        'currency': None,
        'images': [],
        'attributes': None,
        'description': None,
        'product_link': product_link,
        'variants': [],
        'raw_data': {                     
            'care_instructions': []       
        }
    }


            # Product Name
            title_tag = soup.select_one('h1.title')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)


            # SKU
            sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # === Prices ===
            price_div = soup.find('div', class_='new-price')
            if price_div:
                # Extract currency symbol
                currency = None
                def extract_currency(price_text):
                    match = re.match(r'([^\d\s.,]+)', price_text)
                    return match.group(1) if match else None

                def clean_price(price_text):
                    return re.sub(r'[^\d]', '', price_text)

                # Discounted (original) price
                off_price_div = price_div.find('div', class_='off-price')
                if off_price_div:
                    original_price_span = off_price_div.find('span', class_='money')
                    if original_price_span:
                        price_text = original_price_span.get_text(strip=True)
                        product_data['original_price'] = clean_price(price_text)
                        currency = extract_currency(price_text)

                # Sale price
                sale_price_div = price_div.find('div', class_='sale-price')
                if sale_price_div:
                    sale_price_spans = sale_price_div.find_all('span', class_='money')
                    if sale_price_spans:
                        price_text = sale_price_spans[-1].get_text(strip=True)
                        product_data['sale_price'] = clean_price(price_text)
                        if not currency:
                            currency = extract_currency(price_text)
                else:
                    # No sale, only one price
                    price_simple_div = price_div.find('div', class_='price')
                    if price_simple_div:
                        price_span = price_simple_div.find('span', class_='money')
                        if price_span:
                            price_text = price_span.get_text(strip=True)
                            product_data['original_price'] = clean_price(price_text)
                            currency = extract_currency(price_text)

                product_data['currency'] = currency if currency else "PKR"
                      
        

          
           

            visited_urls = set()
            visited_urls.add(product_link)
            base_url = self.base_url if hasattr(self, 'base_url') else product_link
            product_data["images"] = []

            def extract_images_from_soup(soup_obj):
                image_elements = soup_obj.select("div.swiper.thumbswiper img")
                for img in image_elements:
                    src = img.get("src") or img.get("data-src")
                    if src:
                        if src.startswith("//"):
                            src = "https:" + src
                        else:
                            src = urljoin(base_url, src)

                        parsed_url = urlparse(src)
                        query_params = parse_qs(parsed_url.query)
                        query_params.pop("width", None)
                        clean_query = "&".join(f"{k}={v[0]}" for k, v in query_params.items())
                        final_url = urlunparse(parsed_url._replace(query=clean_query))

                        if final_url not in product_data["images"]:
                            product_data["images"].append(final_url)

            # Extract main product images
            extract_images_from_soup(soup)

            # Get variant links
            variant_links = []
            variant_anchors = soup.select("div.new-option-single.color-option a.option-single-value[href]")
            for a in variant_anchors:
                href = a["href"]
                full_url = urljoin(base_url, href)
                if full_url not in visited_urls:
                    variant_links.append(full_url)

            # Extract images from variants
            for variant_url in variant_links:
                visited_urls.add(variant_url)
                variant_resp = requests.get(variant_url)
                variant_resp.raise_for_status()
                variant_soup = BeautifulSoup(variant_resp.text, "html.parser")
                extract_images_from_soup(variant_soup)

            # =====================================

          

            

            # Short Description
            short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
            if short_desc_div:
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                product_data['attributes'] = ' '.join(paragraphs)

            # Product Description
            description_div = soup.select_one('div.draw-content')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                product_data['description'] = '\n\n'.join(paragraphs)

                            # Ensure raw_data key exists
                if 'raw_data' not in product_data:
                    product_data['raw_data'] = {}

                # Scrape care instructions
                care_instructions = []

                care_items = soup.select('div.new-composition-list div.new-composition-single')
                for item in care_items:
                    text_div = item.find('div', class_='text')
                    if text_div:
                        text = text_div.get_text(strip=True)
                        if text:
                            care_instructions.append(text)

                # Save into raw_data
                product_data['raw_data']['care_instructions'] = care_instructions if care_instructions else None

                # === Color Variants ===
                color_section = soup.find("div", class_="new-option-single color-option")
                colors = []

                if color_section:
                    # Handle colors without hrefs
                    for div in color_section.find_all("div", class_="option-single-value"):
                        input_tag = div.find("input")
                        if input_tag:
                            color = input_tag.get("value", "Unknown")
                            colors.append((color, None))

                    # Handle colors with hrefs (different PDP links)
                    for link in color_section.find_all("a", class_="option-single-value"):
                        input_tag = link.find("input")
                        if input_tag:
                            color = input_tag.get("value", "Unknown")
                            href = link.get("href")
                            full_link = urljoin(self.base_url, href)
                            colors.append((color, full_link))

                # Loop through colors and extract size variants
                for color, link in colors:
                    if link:
                        color_response = requests.get(link, headers=self.headers)
                        color_response.raise_for_status()
                        color_soup = BeautifulSoup(color_response.text, 'html.parser')
                    else:
                        color_soup = soup  # Use current soup if no link

                    size_section = color_soup.find("div", class_="new-option-single")
                    if size_section:
                        size_options = size_section.find_all("div", class_="option-single-value")
                        for option in size_options:
                            label = option.find("label")
                            size = label.text.strip() if label else "Unknown"
                            availability = "false" if "sold_out" in option.get("class", []) else "true"

                            product_data['variants'].append({
                                'color': color,
                                'size': size,
                                'availability': availability
                            })


            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}

            
    async def scrape_products_links(self, url):
            all_product_links = set()
            page_number = 1
            current_url = url

            while True:
                try:
                    self.log_info(f"Scraping page {page_number}: {current_url}")
                    response = requests.get(current_url, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')

                    # Find all product <li> tags with class containing 'product__item'
                    product_items = soup.select('li.product__item')

                    if not product_items:
                        self.log_info(f"No product items found on page {page_number}. Stopping.")
                        break

                    initial_count = len(all_product_links)

                    for item in product_items:
                        # Find the first <a> tag inside this <li> with href starting with /products/
                        link_tag = item.find('a', href=True)
                        if link_tag and link_tag['href'].startswith('/products/'):
                            href = link_tag['href']
                            product_url = f"{self.base_url}{href}" if href.startswith('/') else href
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

