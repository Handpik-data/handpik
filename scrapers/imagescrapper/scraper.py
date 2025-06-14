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
    def __init__(self):
        super().__init__(
            base_url="https://pk.image1993.com/",
            logger_name=IMAGE_LOGGER
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))

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
                    'sku': None,
                    'original_price': None,
                    'sale_price': None,
                    'save_percent': None,
                    'currency':None,
                    'images': [],
                    'attributes': {
                        'color': None,        # e.g. "Baby Blue"
                        'color_code': None,   # e.g. "#a7c0d1"
                    },
                    'description ': {},
                    'product_details': {},
                    'breadcrumbs': [],
                    'product_link': product_link,  # assign here
                    'product_care': None,
                    'shipment_info': None,
                    'variants': []  # <-- Correct key and type (list of dicts)
                }
            

            # Product name
            title_tag = soup.select_one('a.product__title > h2.h1')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)
            else:
                self.log_info("Product name not found.")


            # SKU and prices
            sku_element = soup.select_one('p.product__text.inline-richtext.caption-with-letter-spacing')
            if sku_element:
                text = sku_element.get_text(strip=True)
                if 'Article Code :' in text:
                    product_data['sku'] = text.split('Article Code :')[-1].strip()

                
                original_price = sale_price = save_percent = currency = None

                price_container = soup.find('div', class_='price__container')
                if price_container:
                    regular_div = price_container.find('div', class_='price__regular')
                    if regular_div:
                        price_tag = regular_div.find('span', class_='price-item--regular')
                        if price_tag:
                            money_tag = price_tag.find('span', class_='money')
                            if money_tag:
                                text = money_tag.get_text(strip=True)
                                original_price = text

                    sale_div = price_container.find('div', class_='price__sale')
                    if sale_div:
                        sale_tag = sale_div.find('span', class_='price-item--sale')
                        if sale_tag:
                            money_tag = sale_tag.find('span', class_='money')
                            if money_tag:
                                text = money_tag.get_text(strip=True)
                                sale_price = text

                    # Extract numeric values for calculation & detect currency
                    if original_price:
                        try:
                            # Extract currency (non-digit prefix, e.g., PKR, $, Rs)
                            import re
                            currency_match = re.match(r'([^\d]+)', original_price.strip())
                            currency = currency_match.group(1).strip() if currency_match else None

                            orig_val = int(re.sub(r'[^\d]', '', original_price))
                            sale_val = int(re.sub(r'[^\d]', '', sale_price)) if sale_price else None

                            if sale_val and orig_val > sale_val:
                                discount = round(((orig_val - sale_val) / orig_val) * 100)
                                save_percent = f"{discount}%"
                            else:
                                save_percent = None
                        except Exception:
                            save_percent = None
                else:
                    original_price = sale_price = save_percent = currency = None

                # ✅ Save to product_data dictionary
                product_data['original_price'] = original_price
                product_data['sale_price'] = sale_price
                product_data['save_percent'] = save_percent
                product_data['currency'] = currency

           # Images
            product_data['images'] = []  # Ensure it's initialized

            image_elements = soup.select('div.swiper-wrapper img')

            for img in image_elements:
                src = img.get('src')
                if src:
                    # Ensure full URL (handle URLs starting with "//")
                    if src.startswith ('//'):
                        src = 'https:' + src
                    elif not src.startswith('http'):
                        src = urljoin(self.base_url, src)
                    if src not in product_data['images']:
                        product_data['images'].append(src)
           
            # Extract color and color code
            label = soup.find('label', class_='product-form_custom_label Color--label')
            color_name = None
            color_code = None
            if label:
                texts = [t for t in label.stripped_strings]
                visible_texts = [t for t in texts if "Variant sold out" not in t]
                if visible_texts:
                    color_name = visible_texts[0]

                color_span = label.find('span', class_='filter-color-box')
                if color_span and 'style' in color_span.attrs:
                    style = color_span['style']
                    match = re.search(r'background-color:\s*(#[0-9a-fA-F]+)', style)
                    if match:
                        color_code = match.group(1)

            product_data['attributes']['color'] = color_name
            product_data['attributes']['color_code'] = color_code

           # Extract shipment info (separate div with specific ID)
            shipment_div = soup.select_one('div#ProductAccordion-collapsible_tab_8LbGXL-template--24274139414891__main')
            if shipment_div:
                for br in shipment_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in shipment_div.find_all('p')]
                product_data['shipment_info'] = '\n\n'.join(paragraphs)
            else:
                product_data['shipment_info'] = None

            description_div = soup.select_one('div.accordion__content.rte')
            if description_div:
                # Replace <br> tags with newlines
                for br in description_div.find_all('br'):
                    br.replace_with('\n')

                # Extract all <p> tags and clean the text
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]

                # Join paragraphs into a single string with double newlines
                product_data['description '] = '\n\n'.join(paragraphs)
            else:
                product_data['description '] = None

           # Assuming `soup` is already defined using BeautifulSoup(html, 'html.parser')

            # Find all <details> elements
            details_tags = soup.find_all('details')

            product_care = None
            for tag in details_tags:
                summary = tag.find('summary')
                if summary and 'CARE INSTRUCTIONS' in summary.get_text(strip=True).upper():
                    product_care = tag
                    break

            if product_care:
                care_text = []
                
                # Extract paragraph text with <br> as line breaks
                p_tag = product_care.find('p')
                if p_tag:
                    for br in p_tag.find_all('br'):
                        br.replace_with('\n')
                    product_care_text = p_tag.get_text().replace('\xa0', ' ').strip()
                    care_text.extend([line.strip() for line in product_care_text.split('\n') if line.strip()])

                # Extract SVG titles if available
                svg_tags = product_care.find_all('svg')
                for svg in svg_tags:
                    title = svg.find('title')
                    if title:
                        care_text.append(title.get_text(strip=True))

                product_data['product_care'] = care_text if care_text else None
            else:
                product_data['product_care'] = None

            # Extract breadcrumbs from the updated HTML structure
            product_data['breadcrumbs'] = []  # Ensure it's initialized

            breadcrumb_items = soup.select('ul.breadcrumbs__list li.breadcrumbs__item a.breadcrumbs__link')

            for crumb in breadcrumb_items:
                text = crumb.get_text(strip=True)
                if text:
                    product_data['breadcrumbs'].append(text)

                            # Start variant scraping
                variants = []

                # Step 1: Get all color labels
                color_labels = soup.find_all('label', class_='product-form_custom_label Color--label')
                colors = []

                for label in color_labels:
                    color_text = label.get_text(strip=True).replace("Variant sold out or unavailable", "").strip()
                    if color_text:
                        colors.append(color_text)

                # Step 2: Get sizes
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

                # Assign variants into product_data
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
        product_links = await self.scrape_products_links(url)

        for product_link in product_links:
            pdp_data = await self.scrape_pdp(product_link)
            if pdp_data and not pdp_data.get('error'):
                all_products.append(pdp_data)
            await asyncio.sleep(1)

        return all_products

    async def scrape_data(self):
        final_data = []
        try:
            category_urls = await self.get_unique_urls_from_file("categories.txt")

            for url in category_urls:
                self.log_info(f"Scraping category: {url}")
                category_data = await self.scrape_category(url)
                final_data.extend(category_data)

            if final_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                output_filename = f"products_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_filename)

                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)

                self.log_info(f"Saved {len(final_data)} products into {output_filename}")
            else:
                self.log_error("No products scraped.")

        except Exception as e:
            self.log_error(f"Error in scrape_data: {str(e)}")
