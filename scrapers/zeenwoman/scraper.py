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
from utils.LoggerConstants import ZEENWOMAN_LOGGER

class ZeeWomanScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://zeenwoman.com",
            logger_name=ZEENWOMAN_LOGGER,
            proxies=proxies
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "zeenwoman"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        if not os.path.exists(filename):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filename, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))
        
    async def scrape_pdp(self, product_link):
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
            'category': None,
            'product_url': product_link,
            'variants': [],
            'attributes': {},
            'raw_data': {},
        }
        try:
            response = await self.make_request(
                product_link,
                headers=self.headers
            )

            soup = BeautifulSoup(response, 'html.parser')

            product_container = soup.find('div', {'class': 't4s-product__info-container'})
            if not product_container:
                return {'error': 'Product container not found'}

            product_title_element = soup.find('h1', {'class': 't4s-product__title'})
            if product_title_element:
                product_data['title'] = product_title_element.text.strip()

            product_price_info = soup.find('div', {'class': 't4s-product__price-review'})
            if product_price_info:
                price_container = product_price_info.find('div', {'class': 't4s-product-price'})
                if price_container:
                    del_price = price_container.find('del')
                    ins_price = price_container.find('ins')
                    single_price = price_container.find('span', {'class': 'money'})

                    original_price = sale_price = None

                    if del_price and ins_price:
                        original_price = del_price.get_text(strip=True)
                        sale_price = ins_price.get_text(strip=True)
                    elif single_price:
                        original_price = single_price.get_text(strip=True)

                    product_data['original_price'] = original_price
                    product_data['sale_price'] = sale_price

            
            swatch_options = soup.find_all('div', {'class': 't4s-swatch__option'})
            
            for option in swatch_options:
                if 'display: none' in option.get('style', ''):
                    continue
                    
                attr_name = option.find('h4', {'class': 't4s-swatch__title'}).get_text(strip=True)
                values = []
                
                for item in option.find_all('div', {'data-swatch-item': True}):
                    values.append(item.get('data-value', item.get_text(strip=True)))
                
                if values:
                    if len(values) == 1:
                        values = values[0]
                    if attr_name == 'Product Detail':
                        product_data['description'] = values
                    else:
                        product_data['attributes'][attr_name] = values

            description_div = soup.find('div', class_='full description')
            if description_div:
                for p in description_div.find_all('p'):
                    strong = p.find('strong')
                    if not strong:
                        continue
                    key = strong.get_text(strip=True).rstrip(':').strip()
                    lines = []
                    current_line = []
                    for elem in strong.next_siblings:
                        if elem.name == 'br':
                            line = ' '.join(current_line).strip()
                            if line:
                                lines.append(line)
                            current_line = []
                        else:
                            text = elem.get_text(strip=True)
                            if text:
                                current_line.append(text)
                    line = ' '.join(current_line).strip()
                    if line:
                        lines.append(line)
                    if lines:
                        if len(lines) == 1:
                            lines = lines[0]
                        if key == 'Product Detail':
                            product_data['description'] = lines
                        else:
                            product_data['attributes'][key] = lines
                
                specs_container = description_div.find('div', class_='index-tableContainer')
                if specs_container:
                    for row in specs_container.find_all('div', class_='index-row'):
                        key_div = row.find('div', class_='index-rowKey')
                        value_div = row.find('div', class_='index-rowValue')
                        if key_div and value_div:
                            key = key_div.get_text(strip=True)
                            value = value_div.get_text(strip=True)
                            if key == 'Product Detail':
                                product_data['description'] = value
                            else:
                                product_data['attributes'][key] = value

            media_container = soup.find('div', {'class': 't4s-product__media-wrapper'})
                
            if media_container:
                media_items = media_container.find_all('div', {'data-main-slide': True})
                
                for item in media_items:
                    img_tag = item.find('img', {'data-master': True})
                    if img_tag and img_tag.has_attr('data-master'):
                        img_url = img_tag['data-master']
                        img_url = f"https:{img_url}" if img_url.startswith('//') else img_url
                        
                        if img_url not in product_data['images']:
                            product_data['images'].append(img_url)

            variants_tag = soup.find('script', class_='pr_variants_json')
            if variants_tag:
                try:
                    variants_json = json.loads(variants_tag.string.strip())
                except Exception:
                    variants_json = []
            else:
                variants_json = []

            options_tag = soup.find('script', class_='pr_options_json')
            if options_tag:
                try:
                    options_json = json.loads(options_tag.string.strip())
                except Exception:
                    options_json = []
            else:
                options_json = []

            idx_to_optname = {}
            for opt in options_json:
                pos = opt.get('position', 1)
                opt_name = opt.get('name') or f"Option{pos}"
                idx_to_optname[pos] = opt_name

            all_variant_combos = []

            for variant in variants_json:
                combo_dict = {}

                for i in range(1, 11):
                    key_opt = f"option{i}"
                    if key_opt in variant:
                        opt_val = variant[key_opt]
                        if not opt_val:  
                            break

                        attribute_name = idx_to_optname.get(i, f"Option{i}")
                        combo_dict[attribute_name] = opt_val
                    else:
                        break

                combo_dict['availability'] = variant.get("available", False)
                all_variant_combos.append(combo_dict)

            product_data["variants"] = all_variant_combos
        except Exception as e:
            self.log_error(f"Error scraping product data from {product_link}: {e}")   
        return product_data

    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        current_url = url
        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.make_request(
                    current_url,
                    headers=self.headers
                )
                
                soup = BeautifulSoup(response, 'html.parser')
                product_divs = soup.find_all('div', class_='t4s-product')
                
                if not product_divs: 
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
                    
                for product in product_divs:
                    link_tag = product.find('a', class_='t4s-full-width-link')
                    if link_tag and link_tag.has_attr('href'):
                        product_url = f"{self.base_url}{link_tag['href']}"
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)
                
                page_number += 1
                current_url = f"{url}?page={page_number}" if "?" not in url else f"{url}&page={page_number}"
                
            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break
        
        return all_product_links

    async def scrape_category(self, url):
        all_products = []

        all_products_links = await self.scrape_products_links(url)
        for product_link in all_products_links:
            pdp_data = await self.scrape_pdp(product_link)
            if pdp_data is not None:
                all_products.append(pdp_data)
                break
        
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
                break
                
            if final_data:
                saved_path = self.save_data(final_data)
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
                        
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")