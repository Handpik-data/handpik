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
from utils.LoggerConstants import CHINYERE_LOGGER
from urllib.parse import urljoin
import time


class chinyerescraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://www.chinyere.pk/",
            logger_name=CHINYERE_LOGGER
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
            'sku': None,
            'original price': None,
            'sale price': None,
            'currency': None,
            'save_percent': None,
            'images': [],
            'description': None,
            'product_link': product_link,
            'variants': {
                'sizes': [],          
                'all_sizes': [],      
                'visible_sizes': [],  
                'color': None         
            }
        }

            # Product Name
            title_tag = soup.select_one('h1.productView-title')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)


            # SKU
            sku_element = soup.select_one('div.productView-info-item span.productView-info-value')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)


            # Prices
            price_div = soup.find('div', class_='price')
            if price_div:
                currency_symbol = None

                # Try to find sale price (discounted price)
                sale_last_dd = price_div.select_one('div.price__sale dd.price__last span.money')
                if sale_last_dd:
                    sale_text = sale_last_dd.get_text(strip=True)
                    # Extract numeric price
                    product_data['sale_price'] = ''.join(filter(lambda x: x.isdigit() or x == '.', sale_text))
                    # Extract currency
                    currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', sale_text)).strip()

                # Try to find original (compare) price
                compare_dd = price_div.select_one('div.price__sale dd.price__compare span.money')
                if compare_dd:
                    compare_text = compare_dd.get_text(strip=True)
                    product_data['original price'] = ''.join(filter(lambda x: x.isdigit() or x == '.', compare_text))
                    # If no currency detected yet, get it from here
                    if not currency_symbol:
                        currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', compare_text)).strip()

                # If no sale section exists, fallback to regular price
                if 'sale price' not in product_data or product_data['sale price'] is None:
                    regular_dd = price_div.select_one('div.price__regular dd.price__last span.money')
                    if regular_dd:
                        regular_text = regular_dd.get_text(strip=True)
                        product_data['original price'] = ''.join(filter(lambda x: x.isdigit() or x == '.', regular_text))
                        if not currency_symbol:
                            currency_symbol = ''.join(filter(lambda x: not x.isdigit() and x != '.', regular_text)).strip()

                # Save the currency symbol to the product data dictionary
                product_data['currency'] = currency_symbol

            # Color and SKU from style-id section
            style_id_div = soup.select_one('div.new-product-style-id.mobile-hide')
            if style_id_div:
                color_text = ''.join([t for t in style_id_div.contents if isinstance(t, str)]).strip().replace('|', '').strip()
                sku_span = style_id_div.find('span')
                if color_text:
                    product_data['attributes']['color'] = color_text
                if sku_span:
                    product_data['sku'] = sku_span.get_text(strip=True)

           # Initialize images list if not already present
            if 'images' not in product_data:
                product_data['images'] = []

            # Find all divs with class 'media' and having a 'data-fancybox' attribute set to "images"
            media_divs = soup.find_all('div', class_='media', attrs={'data-fancybox': 'images'})

            for media_div in media_divs:
                href = media_div.get('href')
                if href:
                    # Complete URL handling
                    if href.startswith('//'):
                        href = 'https:' + href
                    full_url = urljoin(self.base_url, href)
                    
                    # Avoid duplicates
                    if full_url not in product_data['images']:
                        product_data['images'].append(full_url)

            # Product Description
            description_div = soup.select_one('div#tab-description-mobile')
            if description_div:
                # Replace <br> tags with newlines
                for br in description_div.find_all('br'):
                    br.replace_with('\n')

                # Extract all <p> tags and clean the text
                paragraphs = [p.get_text(separator='\n', strip=True).replace('\xa0', ' ') for p in description_div.find_all('p')]

                # Join paragraphs into a single string with double newlines
                product_data['description'] = '\n\n'.join(paragraphs)
            else:
                product_data['description'] = None


                    # Initialize lists
            all_sizes = []
            visible_sizes = []

            # Select the fieldset that holds size options
            size_fieldset = soup.find('fieldset', {'data-product-attribute': 'set-rectangle'})
            if size_fieldset:
                # Find all size input labels
                size_labels = size_fieldset.find_all('label', class_='product-form__label')
                for label in size_labels:
                    size_text = label.find('span', class_='text')
                    if size_text:
                        size_value = size_text.get_text(strip=True)
                        # Check availability based on label class
                        available = 'soldout' not in label.get('class', [])
                        all_sizes.append({'size': size_value, 'color': None, 'available': available})
                        visible_sizes.append({'size': size_value, 'color': None, 'available': available})

            # Extract color
            color = None
            tab_popup = soup.find('div', class_='tab-popup-content')
            if tab_popup:
                match = re.search(r'Color:\s*([^\s<]+)', tab_popup.get_text())
                if match:
                    color = match.group(1).strip()

            # Update color in sizes
            for size in all_sizes:
                size['color'] = color
            for size in visible_sizes:
                size['color'] = color

            # Create variants from sizes
            variants = []
            for size in all_sizes:
                variants.append({
                    'size': size['size'],
                    'color': size['color'],
                    'availability': size['available']
                })

            # Add sizes and color to product_data
            product_data['color'] = color or None
        
        
            product_data['variants'] = variants or None

          


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

                # Select the first <a> tag with class 'card-link' and href starting with '/products/'
                link_tag = soup.select_one('a.card-link[href^="/products/"]')

                if not link_tag:
                    self.log_info(f"No product link found on page {page_number}. Stopping.")
                    break

                href = link_tag['href']
                product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                all_product_links.add(product_url)

                # Since we only want the first link, break immediately
                break

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

            page_number += 1
            if "?" not in url:
                current_url = f"{url}?page={page_number}"
            else:
                current_url = f"{url}&page={page_number}"

        self.log_info(f"Collected {len(all_product_links)} product link(s).")
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
