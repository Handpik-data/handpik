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
from utils.LoggerConstants import JUNAIDJAMSHED
from urllib.parse import urljoin, urlparse, urlunparse
import time


class juniadjamshed(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://www.junaidjamshed.com/",
            logger_name=JUNAIDJAMSHED
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
        print(product_link)
        try:
            response = requests.get(product_link)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            product_data = {
                'product_name': None,
                'product_title': None,
                'sku': None,
                'product_attribute_sku': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'images': [],
                'attributes': {},
                'description': {},
                'product_information': {},
                'product_details': {},
                'breadcrumbs': [],
                'product_link': product_link,
                'variants': [],
                'all_sizes': [],
                'visible_sizes': [],
                'stock': None,
                'shipping_handling': None
            }

            # Product Name
            title_tag = soup.select_one('h1.page-title > span.base')
            if title_tag:
                product_data['product_name'] = title_tag.get_text(strip=True)

            # Brand
            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            # SKU
            sku_element = soup.select_one('div.product.attribute.sku div.value[itemprop="sku"]')
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # Article Code SKU
            article_code_element = soup.select_one('div.product.attribute.sku.article-code > span')
            if article_code_element:
                product_data['product_attribute_sku'] = article_code_element.get_text(strip=True)

            # Prices
            price_box = soup.select_one('div.price-box')
            if price_box:
                sale_span = price_box.select_one('span.price-wrapper')
                old_price_span = price_box.select_one('span.old-price')

                if sale_span:
                    product_data['sale_price'] = sale_span.get_text(strip=True)

                if old_price_span:
                    original_price = old_price_span.get_text(strip=True)
                    if original_price != product_data.get('sale_price'):
                        product_data['original_price'] = original_price


            image_elements = soup.select('img[src], img[data-src], img[data-original]')

            for img in image_elements:
                src = img.get('src') or img.get('data-src') or img.get('data-original')
                if src and '2090' in src:  # Filter based on known image pattern
                    full_src = urljoin(product_link, src)
                    parsed_url = urlparse(full_src)
                    clean_src = urlunparse(parsed_url._replace(query=""))  # remove ?width=86...
                    if clean_src not in product_data['images']:
                        product_data['images'].append(clean_src)

            # Stock Status
            stock_element = soup.select_one('div.stock.available span')
            if stock_element and stock_element.text.strip().lower() == 'in stock':
                product_data['stock'] = "In stock"
            else:
                product_data['stock'] = "Out of stock"

            # Description
            description_container = soup.find('div', {'class': 'value', 'itemprop': 'description'})
            if description_container:
                raw_text = description_container.get_text(separator='<br>', strip=True)
                lines = raw_text.split('<br>')
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        product_data['description'][key.strip()] = value.strip()
                    else:
                        product_data['description'][line.strip()] = None

            # Product Information Table
            attributes_table = soup.find('table', {'id': 'product-attribute-specs-table'})
            if attributes_table:
                for row in attributes_table.find_all('tr'):
                    th = row.find('th')
                    td = row.find('td')
                    if th and td:
                        product_data['product_information'][th.text.strip()] = td.text.strip()

            # Product Details Section
            details_div = soup.select_one('div.t4s-rte.t4s-tab-content.t4s-active')
            if details_div:
                disclaimer = details_div.select_one('div.tab--disclaimer')
                if disclaimer:
                    disclaimer.decompose()
                for br in details_div.find_all('br'):
                    br.replace_with('\n')

                raw_text = details_div.get_text(separator='\n').strip()
                lines = [line.strip().replace('\xa0', ' ') for line in raw_text.split('\n') if line.strip()]

                details = {}
                current_key = None
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        details[key.strip()] = value.strip()
                        current_key = key.strip()
                    elif current_key:
                        details[current_key] += f" {line}"
                    else:
                        details[line] = None
                product_data['product_details'] = details

            # Breadcrumbs
            breadcrumb_items = soup.select('nav.t4s-pr-breadcrumb a, nav.t4s-pr-breadcrumb span')
            for crumb in breadcrumb_items:
                text = crumb.get_text(strip=True)
                if text:
                    product_data['breadcrumbs'].append(text)

            # Sizes
            all_sizes = []
            visible_sizes = []

            script_tags = soup.find_all('script', type='text/x-magento-init')
            for script_tag in script_tags:
                if '[data-role=swatch-options]' in script_tag.text:
                    try:
                        json_data = json.loads(script_tag.string)
                        swatch_config = json_data.get('[data-role=swatch-options]', {}).get('Magento_Swatches/js/swatch-renderer', {})

                        if 'jsonConfig' in swatch_config:
                            attributes = swatch_config['jsonConfig'].get('attributes', {})
                            for attr_id, attr_data in attributes.items():
                                if attr_data.get('code') == 'size':
                                    for option in attr_data.get('options', []):
                                        value = option.get('value') or option.get('label')
                                        if value:
                                            all_sizes.append(value)

                        elif 'jsonSwatchConfig' in swatch_config:
                            for v in swatch_config['jsonSwatchConfig'].values():
                                if isinstance(v, dict) and 'label' in v:
                                    value = v.get('value') or v['label']
                                    if value:
                                        all_sizes.append(value)

                    except (json.JSONDecodeError, KeyError, AttributeError) as e:
                        print(f"Size extraction error: {e}")

            size_tags = soup.select('div.swatch-option.text')
            visible_sizes = [tag.get_text(strip=True) for tag in size_tags if tag.get_text(strip=True)]

            product_data['all_sizes'] = all_sizes or None
            product_data['visible_sizes'] = visible_sizes or None

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
                product_links = soup.find_all('a', class_='product photo product-item-photo')

                if not product_links:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break

                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        all_product_links.append(product_url)

                page_number += 1
                current_url = f"{url}?p={page_number}" if "?" not in url else f"{url}&p={page_number}"

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
