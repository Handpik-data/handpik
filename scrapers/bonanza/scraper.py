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
from utils.LoggerConstants import BONANZA_LOGGER
from urllib.parse import urljoin, urlparse
import time


class BonanzaScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://bonanzasatrangi.com",
            logger_name=BONANZA_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "bonanza"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")

        filepath = os.path.join(self.module_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")

        with open(filepath, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))

    async def scrape_pdp(self, product_link, category_hierarchy=[]):
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
            'category': category_hierarchy,
            'product_url': product_link,
            'variants': [],
            'attributes': {},
            'raw_data': {}
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                product_title_tag = soup.find('h1', class_='sr4-product__title')
                if product_title_tag:
                    product_data["title"] = product_title_tag.get_text(strip=True)
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Title scrape error: {e}")
                product_data["title"] = None

            try:
                # Find the <div> with class 'sr4-tab-content sr4-active'
                desc_div = soup.find('div', class_='sr4-tab-content sr4-active')
                if desc_div:
                    # Extract all <p> tag texts within this div
                    desc_parts = [p.get_text(separator=" ", strip=True) for p in desc_div.find_all('p')]

                    # Extract <li> items if any (future-proofing)
                    li_parts = [li.get_text(separator=" ", strip=True) for li in desc_div.find_all('li')]

                    # Combine all parts into final description text
                    description_text = "\n".join(desc_parts + li_parts).strip()
                    product_data['description'] = description_text
                else:
                    # Fallback to previous logic: accordion__content
                    accordion_content = soup.find('div', class_='accordion__content')
                    if accordion_content:
                        desc_parts = []
                        for p in accordion_content.find_all('p'):
                            spans = p.find_all('span')
                            if spans:
                                for span in spans:
                                    desc_parts.append(span.get_text(separator=" ", strip=True))
                            else:
                                desc_parts.append(p.get_text(separator=" ", strip=True))
                        product_data['description'] = "\n".join(desc_parts).strip()
                    else:
                        product_data['description'] = ""
            except Exception as e:
                self.log_debug(f"Description scrape error: {e}")
                product_data['description'] = ""



            try:
                attr_div = soup.find('div', class_='accordion__content')
                if attr_div:
                    span_tag = attr_div.find('span', class_='metafield-multi_line_text_field')
                    if span_tag:
                        lines = span_tag.decode_contents().split('<br>')
                        attributes = [BeautifulSoup(line, "html.parser").get_text(strip=True) for line in lines if line.strip()]
                        product_data['attributes']['product_details'] = attributes
            except Exception as e:
                self.log_debug(f"Attributes scrape error: {e}")


            try:
                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price = re.sub(r'[^\d.]', '', text)
                    return price, currency

                # Find the div with class 'sr4-product-price'
                price_div = soup.find('div', class_='sr4-product-price')
                if price_div:
                    # Extract original price from <del> tag
                    original_price_tag = price_div.find('del')
                    if original_price_tag:
                        price_text = original_price_tag.get_text(strip=True)
                        original_price, currency = extract_price(price_text)
                        product_data['original_price'] = original_price
                        product_data['currency'] = currency
                    else:
                        original_price_tag = price_div.find('span', class_='money')
                        product_data['original_price'], currency = extract_price(original_price_tag.get_text(strip=True))

                    # Extract sale price from <ins> tag
                    sale_price_tag = price_div.find('ins')
                    if sale_price_tag:
                        price_text = sale_price_tag.get_text(strip=True)
                        sale_price, currency = extract_price(price_text)
                        product_data['sale_price'] = sale_price
                        product_data['currency'] = currency
                    else:
                        product_data['sale_price'] = None
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                self.log_debug(f"Price scrape error: {e}")

            try:
                variants = []

                # Extract sizes
                size_divs = soup.select('div.sr4-swatch__list div.sr4-swatch__item')
                sizes = []
                for div in size_divs:
                    size_value = div.get('data-value', '').strip()
                    if size_value:
                        sizes.append({
                            'size': size_value,
                            'availability': True  
                        })


                color_divs = soup.select('div.sr4-swatch__list div.sr4-swatch__item.is-sw__color')
                colors = []
                for div in color_divs:
                    color_value = div.get('data-value', '').strip()
                    if color_value:
                        colors.append(color_value)


                if sizes and colors:
                    for size in sizes:
                        for color in colors:
                            variants.append({
                                'size': size['size'],
                                'color': color,
                                'availability': size['availability']
                            })
                elif sizes:
                    for size in sizes:
                        variants.append({
                            'size': size['size'],
                            'color': None,
                            'availability': size['availability']
                        })
                elif colors:
                    for color in colors:
                        variants.append({
                            'size': None,
                            'color': color,
                            'availability': True
                        })

                product_data['variants'] = variants

            except Exception as e:
                return {'error': f'Exception occurred while extracting variants/sizes/colors: {str(e)}', 'product_link': product_link}

            try:
                product_images = []
                img_tags = soup.find_all('img', class_='sr4-lz--fadeIn')

                for img in img_tags:
                    # Try to get the highest resolution from data-master
                    src = img.get('data-master')
                    if not src:
                        # Fallback to data-srcset or srcset if data-master is missing
                        srcset = img.get('data-srcset') or img.get('srcset')
                        if srcset:
                            urls = [s.strip().split(' ')[0] for s in srcset.split(',')]
                            src = urls[-1] if urls else None
                        else:
                            # Fallback to data-src or src
                            src = img.get('data-src') or img.get('src')

                    if src:
                        # Ensure full URL with https:
                        full_url = 'https:' + src if src.startswith('//') else src
                        product_images.append(full_url)

                product_data['images'] = list(set(product_images))  # remove duplicates

            except Exception as e:
                self.log_debug(f"Images scrape error: {e}")


                try:
                    # Initialize raw_data dictionary if not already
                    raw_data = {}

                    # Find the disclaimer div
                    disclaimer_div = soup.find('div', class_='sr4-tab-content', attrs={'data-sr4-tab-content': True})

                    if disclaimer_div:
                        disclaimer_text = disclaimer_div.get_text(strip=True)
                        raw_data['disclaimer'] = disclaimer_text
                    else:
                        raw_data['disclaimer'] = None

                except Exception as e:
                    self.log_debug(f"Disclaimer scrape error: {e}")


        except Exception as e:
            self.log_debug(f"PDP scrape failed: {e}")

        return product_data




    async def scrape_products_links(self, url):
        all_product_links = []
        current_url = url
        page_number = 1
        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')
                main_div = soup.find('div', class_='sr4-main-collection-page')

                if main_div:

                    product_links = soup.find_all('a', class_='sr4-full-width-link')
                    self.log_info(f"{len(product_links)} products on page {page_number}") 
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    for link in product_links:
                        href = link['href']
                        all_product_links.append(self.base_url + href)
                else:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                        
                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"
                

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
        return all_product_links
    

    async def extract_category_hierarchy(self, url):
        from urllib.parse import urlparse
        
        parsed = urlparse(url)
        path_segments = parsed.path.strip('/').split('/')
        
        categories = []
        skip_segments = {'collections'}
        
        for segment in path_segments:
            if segment in skip_segments:
                continue
                
            segment = re.sub(r'-\d+$', '', segment)
            
            if len(segment) < 3 or segment.isdigit():
                continue
                
            category_name = segment.replace('-', ' ').title()
            categories.append(category_name)
        
        return categories

    async def scrape_category(self, url):
        all_products = []
        category_hierarchy = await self.extract_category_hierarchy(url)
        all_products_links = await self.scrape_products_links(url)
        for product_link in all_products_links:
            pdp_data = await self.scrape_pdp(product_link, category_hierarchy)
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
                saved_path = await self.save_data(final_data)
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")