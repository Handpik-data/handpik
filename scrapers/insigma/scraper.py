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
from utils.LoggerConstants import INSIGMA_LOGGER
from urllib.parse import urljoin
import time


class AlkaramScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://insignia.com.pk/",
            logger_name=INSIGMA_LOGGER
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
            async with aiohttp.ClientSession() as session:
                async with session.get(product_link) as response:
                    response.raise_for_status()
                    html = await response.text()

            soup = BeautifulSoup(html, 'html.parser')

            # Initialize product data with all fields
            product_data = {
                'product_name': None,
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'currency': None,
                'sale_percentage': None,
                'images': [],
                'description': None,
                'product_link': product_link,
                'variants': []  
            }

            # Product Name
            h1_tag = soup.select_one('h1')
            if h1_tag:
                product_data['product_name'] = h1_tag.get_text(strip=True)

            # SKU
            sku_element = soup.select_one('span.variant-sku')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # Prices
            original_price_tag = soup.find('s', class_='price-item--regular')
            sale_price_tag = soup.find('span', class_='price-item--sale')
            sale_percent_tag = soup.find('p', class_='save-percentage.price__badge-sale')

            currency = None
            if original_price_tag:
                original_text = original_price_tag.get_text(strip=True)
                product_data['original_price'] = original_text
                currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', original_text)
                if currency_match:
                    currency = currency_match.group(0)

                if sale_price_tag:
                    sale_text = sale_price_tag.get_text(strip=True)
                    product_data['sale_price'] = sale_text
                    if not currency:
                        currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', sale_text)
                        if currency_match:
                            currency = currency_match.group(0)
            else:
                regular_price_tag = soup.find('span', class_='price-item--regular')
                if regular_price_tag:
                    regular_text = regular_price_tag.get_text(strip=True)
                    product_data['original_price'] = regular_text
                    currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', regular_text)
                    if currency_match:
                        currency = currency_match.group(0)

            if sale_percent_tag:
                product_data['sale_percentage'] = sale_percent_tag.get_text(strip=True)

            if currency:
                product_data['currency'] = currency

                 # Images
            product_images = set()

            # Function to normalize and add image URLs
            def add_image_url(url):
                if url:
                    if url.startswith('//'):
                        url = 'https:' + url
                    product_images.add(url)

            # Current page images
            for img in soup.find_all('img', attrs={'data-original-src': True}):
                add_image_url(img['data-original-src'])

            for media_div in soup.find_all('div', class_='product__media'):
                img_tag = media_div.find('img')
                if img_tag:
                    srcset = img_tag.get('srcset', '')
                    largest_url = ''
                    largest_width = 0
                    if srcset:
                        for entry in srcset.split(','):
                            parts = entry.strip().split(' ')
                            if len(parts) >= 2:
                                url, width_str = parts[0], parts[1].replace('w', '')
                                try:
                                    width = int(width_str)
                                    if width > largest_width:
                                        largest_width = width
                                        largest_url = url
                                except ValueError:
                                    continue
                        add_image_url(largest_url)
                    else:
                        add_image_url(img_tag.get('src'))

            # ALSO: check image updates for other color variants
            base_url = "https://insignia.com.pk"
            color_links = soup.select('fieldset.option_color a[href]')

            for a in color_links:
                color_href = a['href']
                color_url = base_url + color_href

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(color_url) as color_response:
                            color_html = await color_response.text()
                            color_soup = BeautifulSoup(color_html, 'html.parser')

                            # Extract images from color page
                            for img in color_soup.find_all('img', attrs={'data-original-src': True}):
                                add_image_url(img['data-original-src'])

                            for media_div in color_soup.find_all('div', class_='product__media'):
                                img_tag = media_div.find('img')
                                if img_tag:
                                    srcset = img_tag.get('srcset', '')
                                    largest_url = ''
                                    largest_width = 0
                                    if srcset:
                                        for entry in srcset.split(','):
                                            parts = entry.strip().split(' ')
                                            if len(parts) >= 2:
                                                url, width_str = parts[0], parts[1].replace('w', '')
                                                try:
                                                    width = int(width_str)
                                                    if width > largest_width:
                                                        largest_width = width
                                                        largest_url = url
                                                except ValueError:
                                                    continue
                                        add_image_url(largest_url)
                                    else:
                                        add_image_url(img_tag.get('src'))
                except Exception as e:
                    self.log_error(f"Error loading images for color variant: {color_url} -> {str(e)}")

            product_data['images'] = list(product_images)
            # Description
            description_section = soup.find('div', class_='product__description.rte.quick-add-hidden')
            if description_section:
                paragraphs = description_section.find_all('p')
                description = '\n'.join(p.get_text(separator="\n", strip=True) for p in paragraphs)
                product_data['description'] = description.strip()

          
            # ----- Variant Extraction -----
            current_color_element = soup.select_one('.option_color strong.active__value')
            current_color = current_color_element.text.strip() if current_color_element else "N/A"

            # Process current color variants
            all_size_elements = soup.select('fieldset.option_size input[type="radio"]')
            is_available = soup.select_one('.product-form__submit')
            base_available = is_available and 'Add to cart' in is_available.text.strip()

            for size_input in all_size_elements:
                size_value = size_input.get('value')
                if not size_value:
                    continue
                    
                is_disabled = 'disabled' in size_input.get('class', [])
                availability = 'Available' if (not is_disabled and base_available) else 'Unavailable'
                
                product_data['variants'].append({
                    'color': current_color,
                    'size': size_value,
                    'availability': availability
                })

            # Process other color variants
            other_color_links = soup.select('fieldset.option_color a[data-color][href]')
            other_colors = {
                link.get('data-color').strip(): link.get('href')
                for link in other_color_links
                if link.get('data-color') and link.get('href') and link.get('data-color').strip() != current_color
            }

            for color_name, color_url in other_colors.items():
                try:
                    full_url = 'https://insignia.com.pk' + color_url if not color_url.startswith('http') else color_url
                    async with aiohttp.ClientSession() as session:
                        async with session.get(full_url) as color_response:
                            color_html = await color_response.text()
                            color_soup = BeautifulSoup(color_html, 'html.parser')
                            
                            # Process availability for this color
                            color_available = color_soup.select_one('.product-form__submit')
                            color_base_available = color_available and 'Add to cart' in color_available.text.strip()
                            
                            for size_input in color_soup.select('fieldset.option_size input[type="radio"]'):
                                size_value = size_input.get('value')
                                if not size_value:
                                    continue
                                    
                                is_disabled = 'disabled' in size_input.get('class', [])
                                availability = 'Available' if (not is_disabled and color_base_available) else 'Unavailable'
                                
                                product_data['variants'].append({
                                    'color': color_name,
                                    'size': size_value,
                                    'availability': availability
                                })
                                
                except Exception as e:
                    self.log_error(f"Error loading color variant {color_url}: {str(e)}")
                    continue

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

                    # Select all <a> tags with class 'full-unstyled-link' and href containing '/products/'
                    product_links = soup.select('a.full-unstyled-link[href*="/products/"]')

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
                    # Build next page url with ?page= or &page= depending on existing query params
                    if "?" not in url:
                        current_url = f"{url}?page={page_number}"
                    else:
                        current_url = f"{url}&page={page_number}"

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
