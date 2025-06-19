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
from utils.LoggerConstants import IMAGE_LOGGER
from urllib.parse import urljoin
import time


class ImageScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://pk.image1993.com/",
            logger_name=IMAGE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "image"
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
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(product_link) as response:
                    if response.status != 200:
                        self.log_error(f"Failed to get product page: {product_link} Status: {response.status}")
                        return {'error': 'Failed to fetch product page', 'product_link': product_link}
                    html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            product_data = {
                'title': None,
                'store_name':'Image',
                'availability':None,
                'brand':None,
                'category':None,
                'category': None,
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'currency': None,
                'images': [],
                'attributes': {},
                'description': None,
                'breadcrumbs': [],
                'product_link': product_link,
                'raw_data': {},
                'variants': []
            }

            # Product name
            title_tag = soup.select_one('a.product__title > h2.h1')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)
            else:
                self.log_info("Product name not found.")
           
           
            # Breadcrumbs
            breadcrumb_items = soup.select('ul.breadcrumbs__list li.breadcrumbs__item a.breadcrumbs__link')
            breadcrumbs = []
            for crumb in breadcrumb_items:
                text = crumb.get_text(strip=True)
                if text:
                    breadcrumbs.append(text)

            if breadcrumbs:
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            # Category
            category_text = None
            breadcrumb_tags = soup.select('a.breadcrumbs__link[aria-current="page"]')
            for tag in breadcrumb_tags:
                href = tag.get('href', '')
                if '/collections/' in href:
                    category_text = tag.get_text(strip=True)
                    break
            product_data['category'] = category_text

            # SKU
            sku_element = soup.select_one('p.product__text.inline-richtext.caption-with-letter-spacing')
            if sku_element:
                text = sku_element.get_text(strip=True)
                if 'Article Code :' in text:
                    product_data['sku'] = text.split('Article Code :')[-1].strip()

            # Prices
            original_price = sale_price = save_percent = currency = None
            price_wrapper = soup.find('div', class_='price__sale')
            if price_wrapper:
                original_tag = price_wrapper.select_one('.price-item--regular .money')
                sale_tag = price_wrapper.select_one('.price-item--sale .money')

                if original_tag and sale_tag:
                    original_price_str = original_tag.get_text(strip=True)
                    sale_price_str = sale_tag.get_text(strip=True)

                    original_price_match = re.findall(r'[\d,]+', original_price_str)
                    sale_price_match = re.findall(r'[\d,]+', sale_price_str)

                    original_price = original_price_match[0] if original_price_match else None
                    sale_price = sale_price_match[0] if sale_price_match else None

                elif sale_tag and not original_tag:
                    sale_price_str = sale_tag.get_text(strip=True)
                    sale_price_match = re.findall(r'[\d,]+', sale_price_str)
                    original_price = sale_price_match[0] if sale_price_match else None
                    sale_price = None

                if original_price:
                    try:
                        currency_match = re.match(r'([^\d]+)', original_price_str.strip())
                        currency = currency_match.group(1).strip() if currency_match else None

                        orig_val = int(re.sub(r'[^\d]', '', original_price_str))
                        sale_val = int(re.sub(r'[^\d]', '', sale_price_str)) if sale_price else None

                        if sale_val and orig_val > sale_val:
                            discount = round(((orig_val - sale_val) / orig_val) * 100)
                            save_percent = f"{discount}%"
                    except Exception:
                        save_percent = None

            product_data['original_price'] = original_price
            product_data['sale_price'] = sale_price
            product_data['save_percent'] = save_percent
            product_data['currency'] = currency

            # Images
            image_elements = soup.select('div.swiper-wrapper img')
            for img in image_elements:
                src = img.get('src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    if src not in product_data['images']:
                        product_data['images'].append(src)

            # Color (for variant logic only)
            color_name = None
            color_code = None
            label = soup.find('label', class_='product-form_custom_label Color--label')
            if label:
                texts = [t for t in label.stripped_strings if "Variant sold out" not in t]
                if texts:
                    color_name = texts[0]

                color_span = label.find('span', class_='filter-color-box')
                if color_span and 'style' in color_span.attrs:
                    style = color_span['style']
                    match = re.search(r'background-color:\s*(#[0-9a-fA-F]+)', style)
                    if match:
                        color_code = match.group(1)

            # Description
            description_div = soup.select_one('div.accordion__content.rte')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                product_data['description'] = '\n\n'.join(paragraphs)

            # Shipment Info
            shipment_text = None
            shipment_div = soup.select_one('div#ProductAccordion-collapsible_tab_8LbGXL-template--24274139414891__main')
            if shipment_div:
                for br in shipment_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in shipment_div.find_all('p')]
                shipment_text = '\n\n'.join(paragraphs)

            # Product Care
            product_care_text = None
            details_tags = soup.find_all('details')
            for tag in details_tags:
                summary = tag.find('summary')
                if summary and 'CARE INSTRUCTIONS' in summary.get_text(strip=True).upper():
                    p_tag = tag.find('p')
                    if p_tag:
                        for br in p_tag.find_all('br'):
                            br.replace_with('\n')
                        product_care_text = p_tag.get_text(strip=True).replace('\xa0', ' ').strip()
                    break

            # Raw Data
            product_data['raw_data'] = {
                'product_care': product_care_text,
                'shipment_info': shipment_text
            }

            # Variants
            variants = []
            color_labels = soup.find_all('label', class_='product-form_custom_label Color--label')
            colors = []
            for label in color_labels:
                color_text = label.get_text(strip=True).replace("Variant sold out or unavailable", "").strip()
                if color_text:
                    colors.append(color_text)

            size_fieldset = soup.find('fieldset', class_='custom-option-size')
            if size_fieldset and colors:
                size_inputs = size_fieldset.find_all('input', {'name': 'Size', 'type': 'radio'})
                for input_tag in size_inputs:
                    size_value = input_tag.get('value', '').strip()
                    is_disabled = input_tag.has_attr('disabled') or 'disabled' in input_tag.get('class', [])
                    available = not is_disabled

                    input_id = input_tag.get('id')
                    label = size_fieldset.find('label', {'for': input_id})
                    size_label = label.get_text(strip=True).replace("Variant sold out or unavailable", "").strip() if label else size_value

                    for color in colors:
                        variants.append({
                            'size': size_label,
                            'color': color,
                            'available': available
                        })

            product_data['variants'] = variants if variants else None

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}


    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1

        async with aiohttp.ClientSession(headers=self.headers) as session:
            while True:
                try:
                    current_url = f"{url}?page={page_number}"
                    self.log_info(f"Scraping page {page_number}: {current_url}")
                    
                    async with session.get(current_url, timeout=10) as response:
                        if response.status != 200:
                            self.log_error(f"Failed to fetch page {page_number}. Status: {response.status}")
                            break

                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')

                        # Find product links on this page
                        link_tags = soup.select('a.card__link-product[href^="/products/"]')

                        if not link_tags:
                            self.log_info(f"No product links found on page {page_number}. Stopping.")
                            break

                        for tag in link_tags:
                            href = tag.get('href')
                            if href:
                                full_url = urljoin(self.base_url, href)
                                all_product_links.add(full_url)

                        page_number += 1
                        await asyncio.sleep(1)  # Avoid hitting server too fast
                except asyncio.TimeoutError:
                    self.log_error(f"Timeout while scraping page {page_number}.")
                    break
                except Exception as e:
                    self.log_error(f"Unexpected error on page {page_number}: {str(e)}")
                    break

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
