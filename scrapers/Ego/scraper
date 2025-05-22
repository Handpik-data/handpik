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
from utils.LoggerConstants import Ego_LOGGER
from urllib.parse import urljoin
import time


class EgoScrapper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://wearego.com/",
            logger_name=Ego_LOGGER
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
                'product_name': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'images': [],
                'description': {},
                'breadcrumbs': [],
                'product_link': product_link,
                'sizes': [],
                'stock': None,
                'product__policies': None,        # 👈 You are right, initialized as None
                'shipping_msg': None 
            }

            # Title extraction
            # Product Title
            title_tag = (
                soup.select_one('h1.productView-title span')  # more targeted
            )
            if title_tag:
                product_data['product_name'] = title_tag.get_text(strip=True)

            # SKU extraction
            sku_element = (
                soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value') or
                soup.select_one('div.product-sku span.variant-sku')
            )
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)
            # Estimated delivery message extraction
            
            shipping_msg_tag = (
                soup.select_one('p.shippingMsg') or
                soup.select_one('p.shippingMsg.mb25')
            )
            if shipping_msg_tag:
                # Extract the full plain text, preserving the date range
                shipping_msg = shipping_msg_tag.get_text(separator=' ', strip=True)
                product_data['shipping_msg'] = shipping_msg


            breadcrumb_nav = (
                soup.select_one('div.bredcrumbWrap nav.breadcrumbs') or
                soup.select_one('nav.page-width.breadcrumbs')
            )
            breadcrumbs = []
            if breadcrumb_nav:
                # Get all <a> and <span> inside the nav (exclude symbols maybe)
                for element in breadcrumb_nav.find_all(['a', 'span'], recursive=False):
                    # Skip separator spans like those with class 'symbol'
                    if element.name == 'span' and 'symbol' in element.get('class', []):
                        continue
                    text = element.get_text(strip=True)
                    if text:
                        breadcrumbs.append(text)


            product_data['breadcrumbs'] = " > ".join(breadcrumbs)


            # Pricing
           # Pricing extraction (handles both sale and non-sale cases)
            price_div = (
                soup.find('div', id=lambda x: x and x.startswith('pricetemplate')) or
                soup.find('div', class_='psinglePriceWr')
            )

            if price_div:
                # Extract sale price
                sale_price_tag = price_div.select_one('span.psinglePrice.sale .money') or price_div.select_one('span.psinglePrice .money')
                if sale_price_tag:
                    product_data['sale_price'] = sale_price_tag.get_text(strip=True)

                # Extract original (crossed) price
                original_price_tag = price_div.select_one('s.psinglePrice .money')
                if original_price_tag:
                    product_data['original_price'] = original_price_tag.get_text(strip=True)

                # If original price is missing, assume no discount
                if (not product_data.get('original_price')) and product_data.get('sale_price'):
                    product_data['original_price'] = product_data['sale_price']
                    product_data['sale_price'] = None  # No sale

                # Extract save percent (if present)
                discount_percent = price_div.select_one('span.discount-badge .off span')
                if discount_percent:
                    product_data['save_percent'] = discount_percent.get_text(strip=True) + '%'
                else:
                    product_data['save_percent'] = None



            product_data['images'] = []

            # First try original selector
            image_links = soup.select('a.pr_photo')

            # If no images found with original selector, try the new selector
            if not image_links:
                image_links = soup.select('div.pr_thumbs_item a.gitem-img')

            for a_tag in image_links:
                # For original selector, try data-zoom attribute; for new selector, use href attribute
                zoom_src = a_tag.get('data-zoom') or a_tag.get('href')
                if zoom_src:
                    # Ensure URL has scheme (https:)
                    full_url = urljoin('https:', zoom_src)
                    if full_url not in product_data['images']:
                        product_data['images'].append(full_url)

                # Stock availability
                stock_element = soup.select_one('div.product-stock span.stockLbl') or soup.select_one('span.stockLbl.instock')
                if stock_element:
                    product_data['stock'] = stock_element.get_text(strip=True)
                else:
                    product_data['stock'] = None

            # Product policies extraction
            policy_div = soup.select_one('div.product__policies.rte') or soup.select_one('p.shippingMsg.mb25')
            if policy_div:
                # Replace <br> with newlines (if any in future)
                for br in policy_div.find_all('br'):
                    br.replace_with('\n')

                # Get the full text, including "Tax included. Shipping calculated at checkout."
                policy_text = policy_div.get_text(separator=' ', strip=True)
                product_data['product__policies'] = policy_text

            # Product description extraction
            desc_div = soup.select_one('div.product-single__description.rte') or soup.select_one('div.product-single__description.rte')
            if desc_div:
                # Replace <br> tags with newline characters
                for br in desc_div.find_all('br'):
                    br.replace_with('\n')

                # Get the text with newlines, then clean multiple newlines and extra spaces
                raw_text = desc_div.get_text(separator='\n')
                # Clean up and keep only meaningful lines
                lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
                description_text = '\n'.join(lines)  # Ensure only single \n between lines

                product_data['description']['full_description'] = description_text

            # SIZE EXTRACTION

            # 1. Try dropdown
                size_select = soup.find('select[name="size"]')
                if size_select:
                    product_data['sizes'] = [option.get_text(strip=True)
                                            for option in size_select.find_all('option')
                                            if option.get('value') and option.get_text(strip=True)]

                # 2. JSON in script tags
                if not product_data['sizes']:
                    script_tags = soup.find_all('script', type='application/json')
                    for script_tag in script_tags:
                        try:
                            json_data = json.loads(script_tag.string)
                            if 'product' in json_data:
                                variants = json_data['product'].get('variants', [])
                                sizes = list({variant.get('option1') for variant in variants if variant.get('option1')})
                                if sizes:
                                    product_data['sizes'] = sizes
                                    break
                        except Exception:
                            continue

                # 3. JavaScript product object
                if not product_data['sizes']:
                    script_tags = soup.find_all('script')
                    for script_tag in script_tags:
                        if 'var product' in script_tag.text:
                            try:
                                match = re.search(r'var product\s*=\s*({.*?});', script_tag.text, re.DOTALL)
                                if match:
                                    product_json = json.loads(match.group(1))
                                    variants = product_json.get('variants', [])
                                    sizes = list({variant.get('option1') for variant in variants if variant.get('option1')})
                                    if sizes:
                                        product_data['sizes'] = sizes
                                        break
                            except Exception:
                                continue

                # 4. Fallback: swatch-element[data-value]
                if not product_data['sizes']:
                    swatch_elements = soup.select('div.swatch-element[data-value]')
                    
                    # Added fallback to check inside special swatch container if no swatch elements found
                    if not swatch_elements:
                        swatch_container = soup.select_one('div.swatch.pvOpt0.fl.f-wrap.option1.mb15.w_100')
                        if swatch_container:
                            swatch_elements = swatch_container.select('div.swatch-element[data-value]')

                    if swatch_elements:
                        product_data['sizes'] = [el['data-value'] for el in swatch_elements if el.get('data-value')]

                # 5. Fallback: swatch-option.text
                if not product_data['sizes']:
                    size_tags = soup.select('div.swatch-option.text')
                    if size_tags:
                        product_data['sizes'] = [tag.get_text(strip=True) for tag in size_tags if tag.get_text(strip=True)]

                return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {
                'error': str(e),
                'product_link': product_link,
                'sizes': []
            }

            
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

                # ✅ This will match the anchor tag correctly
                product_links = soup.select('a.gimg-link[href^="/products/"]')

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = f"{self.base_url}{href}" if href.startswith('/') else href
                        all_product_links.append(product_url)

                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

        self.log_info(f"Collected {len(all_product_links)} product links.")
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
