import os
import re
import json
import asyncio
import re
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import almirah_logger
from urllib.parse import urljoin
import time


class AlkaramScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://almirah.com.pk/pages/men",
            logger_name=almirah_logger
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
            response = requests.get(product_link)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
            'title': None,
            'product_title': None,
            'original_price': None,
            'sale_price': None,
            'currency':None,
            'images': [],
            'description': {},
            'attributes': None,   
            'product_link': product_link,
            'variants': [],
        }

            # Product Name
            title_div = soup.select_one('div.product__title')

            product_name = None
            if title_div:
                # Try <h1> inside it
                h1_tag = title_div.find('h1')
                if h1_tag:
                    product_name = h1_tag.get_text(strip=True)
                else:
                    # fallback: try the <h2 class="h1"> inside <a class="product__title">
                    h2_tag = title_div.select_one('a.product__title h2.h1')
                    if h2_tag:
                        product_name = h2_tag.get_text(strip=True)

            if product_name:
                product_data['title'] = product_name


            # Product Title / Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

                        # Prices
            price_wrapper = soup.find('div', class_='price--show-badge')
            if price_wrapper:
                # Regular price (struck-through or regular)
                regular_price = price_wrapper.select_one('.price__regular .money')
                if regular_price:
                    original_price_str = regular_price.get_text(strip=True)
                    product_data['original_price'] = original_price_str
                else:
                    original_price_str = None

                # Sale price
                sale_price_tag = price_wrapper.select_one('.price__sale .price-item--sale .money')
                if sale_price_tag:
                    sale_price_str = sale_price_tag.get_text(strip=True)
                    product_data['sale_price'] = sale_price_str
                else:
                    sale_price_str = None
                    product_data['sale_price'] = None

                # Extract currency symbol from the first available price
                sample_price = original_price_str or sale_price_str
                if sample_price:
                    match = re.match(r'^(\D+)', sample_price)
                    currency_symbol = match.group(1).strip() if match else None
                    product_data['currency'] = currency_symbol  # ✅ Save currency in dictionary
                else:
                    product_data['currency'] = None

                # Helper to parse price string like 'Rs.6,450.00' to float
                def parse_price(price_str):
                    if not price_str:
                        return None
                    # Remove non-digit and non-dot characters
                    cleaned = re.sub(r'[^\d.]', '', price_str)
                    parts = cleaned.split('.')
                    if len(parts) > 2:
                        # Join everything after the first dot as decimal part
                        cleaned = parts[0] + '.' + ''.join(parts[1:])
                    return float(cleaned)


                original_price = parse_price(original_price_str)
                sale_price = parse_price(sale_price_str)

                # Determine save_percent based on prices
                if original_price is not None and sale_price is not None and sale_price < original_price:
                    # Calculate discount percentage
                    saved_percent = ((original_price - sale_price) / original_price) * 100
                    product_data['save_percent'] = f"{saved_percent:.0f} % off"
                else:
                    # No discount
                    product_data['save_percent'] = None
                    if sale_price is None or sale_price >= original_price:
                        product_data['sale_price'] = None


            additional_info = {}

            # Find the <details> element by its id or class (use a part of the id or class if it changes)
            details = soup.find('details', id=lambda x: x and x.startswith('Details-additional_information'))

            if details:
                # Find the table inside the details
                table = details.find('table')
                if table:
                    # Iterate over each row <tr> in the table body
                    for row in table.find_all('tr'):
                        # Get all <td> cells in the row
                        cells = row.find_all('td')
                        if len(cells) == 2:
                            key = cells[0].get_text(strip=True)   # e.g. "Color"
                            value = cells[1].get_text(strip=True) # e.g. "Grey"
                            additional_info[key] = value

            # Save it to your product_data dict
            product_data['attributes'] = additional_info

                    # Find the media gallery
            media_gallery = soup.find('media-gallery')

            if media_gallery:
                image_tags = media_gallery.find_all('img')
                for img in image_tags:
                    src = img.get('src')
                    if src:
                        # Fix protocol-relative URLs starting with //
                        if src.startswith('//'):
                            src = 'https:' + src
                        # Join relative URLs with base URL
                        full_url = urljoin(self.base_url, src)
                        if full_url not in product_data['images']:
                            product_data['images'].append(full_url)


             # Installment Info
            installment_info = soup.find('div', class_='installment-info')
            if installment_info:
                installment_price_tag = installment_info.find('span', class_='installment-price')
                installment_note_tag = installment_info.find('span', class_='installment-note')

                installment_price = installment_price_tag.get_text(strip=True) if installment_price_tag else None
                installment_note = installment_note_tag.get_text(strip=True) if installment_note_tag else None

                product_data['installment_info'] = {
                    'installment_price': installment_price,
                    'installment_note': installment_note
                }
            else:
                product_data['installment_info'] = None
            # Find the hidden review badge div inside the main widget
            review_div = soup.find('div', class_='jdgm-prev-badge')

            if review_div:
                # Extract average rating (string), convert to float
                avg_rating = review_div.get('data-average-rating', '0')
                product_data['star_rating'] = float(avg_rating) if avg_rating else None

                # Extract number of reviews, convert to int
                num_reviews = review_div.get('data-number-of-reviews', '0')
                product_data['reviews'] = int(num_reviews) if num_reviews.isdigit() else 0

                # Extract number of questions, convert to int if possible
                num_questions = review_div.get('data-number-of-questions', '0')
                # If number of questions is not a digit, fallback to 0
                product_data['number_of_questions'] = int(num_questions) if num_questions.isdigit() else 0

            else:
                # Defaults if the review div not found
                product_data['star_rating'] = None
                product_data['reviews'] = 0
                product_data['number_of_questions'] = 0

            # Shipping and Returns
            drawer_div = soup.select_one('div#scDraw')
            if drawer_div:
                shipping_returns_div = drawer_div.select_one('div.draw-content')
                if shipping_returns_div:
                    paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in shipping_returns_div.find_all('p')]
                    shipping_returns_text = '\n\n'.join(paragraphs)
                    product_data['shipping_and_returns'] = shipping_returns_text
                else:
                    product_data['shipping_and_returns'] = None
            else:
                product_data['shipping_and_returns'] = None

            # Short Description
            short_desc_div = soup.select_one('div.new-product-short-description .metafield-rich_text_field')
            if short_desc_div:
                paragraphs = [p.get_text(strip=True).replace('\xa0', ' ') for p in short_desc_div.find_all('p')]
                product_data['attributes'] = ' '.join(paragraphs)

            # Product Description
            description_div = soup.select_one('div.accordion__content.rte')
            if description_div:
                for br in description_div.find_all('br'):
                    br.replace_with('\n')
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]
                product_data['description'] = '\n\n'.join(paragraphs)


                # Initialize empty list for variants
                variants = []

                # Extract color from the product info table
                color = None
                info_section = soup.select_one('div.accordion__content.additional-info.rte')

                if info_section:
                    rows = info_section.select('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2 and cells[0].text.strip().lower() == 'color':
                            color = cells[1].get_text(strip=True)
                            break

                # Now extract sizes and map them with color + availability
                size_fieldset = soup.select_one('fieldset.product-form__input--pill.size')

                if size_fieldset and color:
                    size_inputs = size_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in size_inputs:
                        size_value = input_tag.get('value')
                        if size_value:
                            is_disabled = 'disabled' in input_tag.attrs or 'disabled' in input_tag.get('class', [])
                            availability = "Sold Out" if is_disabled else "Available"
                            variants.append({
                                "color": color,
                                "size": size_value,
                                "availability": availability
                            })

                # Save variants into product data
                product_data['variants'] = variants or None


            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}
    

    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = requests.get(current_url, headers=self.headers, timeout=10)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')

                # Look for <a class="custom-product-link-wrap" href="/products/...">
                product_links = soup.select('a.custom-product-link-wrap[href^="/products/"]')

                if not product_links:
                    self.log_info(f"No product links found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        self.log_info(f"Collected {len(all_product_links)} unique product links.")
        return all_product_links
    
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
