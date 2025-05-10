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
from utils.LoggerConstants import KHADDI_LOGGER
from urllib.parse import urljoin

class KhaddiScrapper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://pk.khaadi.com/",
            logger_name=KHADDI_LOGGER
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
                'product_title': None,
                'sku': None,
                'original_price': None,
                'sale_price': None,
                'save_percent': None,
                'images': [],
                'attributes': {},
                'description': {},
                'product_details': {},
                'breadcrumbs': [],
                'product_link': product_link,
                'variants': [],
                'sizes': []
            }

            product_container = soup.find('div', {'class': 'product-detail'})
            if not product_container:
                return {'error': 'Product container not found', 'product_link': product_link}

            title_tag = soup.select_one('h1.product-name, h2.product-name')
            if title_tag:
                    product_data['product_name'] = title_tag.get_text(strip=True)
            

            product_title_element = soup.find('div', {'class': 'product-brand'})
            if product_title_element:
                product_data['product_title'] = product_title_element.text.strip()

            sku_element = soup.find('div', {'class': 'product-number'})
            if sku_element and sku_element.find('span'):
                product_data['sku'] = sku_element.find('span').text.strip()

            # Pricing
            del_price = soup.find('span', style=lambda value: value and 'line-through' in value)
            ins_price = soup.find('span', {'content': True})

            original_price = sale_price = save_percent = None

            if del_price and ins_price:
                original_price = del_price.get_text(strip=True)
                sale_price = ins_price.get_text(strip=True)
            elif ins_price:
                original_price = ins_price.get_text(strip=True)

            sales_container = soup.find('span', class_='sales')
            if sales_container:
                price_span = sales_container.find('span', class_='value cc-price')
                if price_span:
                    original_price = price_span.get_text(strip=True)

            badge = soup.find('span', {'class': 'sales'})
            if badge:
                match = re.search(r"SAVE\s+(\d+)%", badge.text.strip(), re.IGNORECASE)
                save_percent = match.group(1) if match else None

            product_data['original_price'] = original_price
            product_data['sale_price'] = sale_price
            product_data['save_percent'] = save_percent

            # Images
            image_elements = soup.select('.pdp-image-carousel .item img')
            for img in image_elements:
                src = img.get('src') or img.get('data-src')
                if src and src not in product_data['images']:
                    product_data['images'].append(urljoin(self.base_url, src))

            # Description
            for attr in soup.select('.spec-list li'):
                strong = attr.find('strong')
                if strong:
                    key = strong.text.strip().replace(':', '')
                    value = attr.text.strip().replace(strong.text.strip(), '').strip()
                    product_data['description'][key] = value

            # Details
            for section in soup.select('.spec-list-title'):
                title = section.text.strip()
                ul = section.find_next('ul')
                details = {}
                if ul:
                    for li in ul.find_all('li'):
                        strong = li.find('strong')
                        if strong:
                            key = strong.text.strip().replace(':', '')
                            value = li.text.strip().replace(strong.text.strip(), '').strip()
                            details[key] = value
                        else:
                            text = li.text.strip()
                            if text:
                                details[text] = None
                    product_data['product_details'][title] = details

            # Breadcrumbs
            breadcrumb_items = soup.select('ol.asset-breadcrumb li.breadcrumb-item a span')
            for crumb in breadcrumb_items:
                text = crumb.get_text(strip=True)
                if text:
                    product_data['breadcrumbs'].append(text)

            # Sizes
                size_items = soup.select('.size-item')
                sizes = []

                for size_item in size_items:
                    size_value = size_item.find('input', {'type': 'radio'})
                    if size_value:
                        size = size_value.get('data-attr-value')
                        size_url = size_value.get('value')
                        if size:
                            sizes.append({
                                'size': size,
                                'url': 'https://pk.khaadi.com' + size_url if size_url.startswith('/') else size_url
                            })

                product_data['sizes'] = sizes

            return product_data

        except Exception as e:
            self.log_error(f"Error scraping PDP {product_link}: {str(e)}")
            return {'error': str(e), 'product_link': product_link}

    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        start = 0
        products_on_page = 49

        while True:
            try:
                paginated_url = f"{url}?start={start}&sz={products_on_page}"
                start = products_on_page
                products_on_page += products_on_page
                self.log_info(f"Scraping page {page_number}: {paginated_url}")
                response = requests.get(paginated_url, headers=self.headers, timeout=10)
                response.raise_for_status()

                soup = BeautifulSoup(response.text, 'html.parser')
                link_tags = soup.find_all('a', class_='plp-tap-mobile plpRedirectPdp')

                if not link_tags:
                    self.log_info(f"No products found on page {page_number}, stopping.")
                    break

                for tag in link_tags:
                    if tag.has_attr('href'):
                        product_url = urljoin(self.base_url, tag['href'])
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                page_number += 1

            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break

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
