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
                'title': None,
                'original_price': None,
                'sale_price': None,
                'images': [],
                'description': {},
                'product_link': product_link,
                'variants': [],
                'stock': None,
                'sku': None
            }

            # Title
            title_tag = soup.select_one('h1.product-single__title.ttlTxt.tt-u.mb15')
            if title_tag:
                product_data['title'] = title_tag.get_text(strip=True)

            # SKU
            sku_element = (
                soup.select_one('div.t4s-sku-wrapper span.t4s-sku-value') or
                soup.select_one('div.product-sku span.variant-sku')
            )
            if sku_element:
                product_data['sku'] = sku_element.get_text(strip=True)

            # Shipping Message
            shipping_msg_tag = (
                soup.select_one('p.shippingMsg') or
                soup.select_one('p.shippingMsg.mb25')
            )
            if shipping_msg_tag:
                product_data['shipping_msg'] = shipping_msg_tag.get_text(separator=' ', strip=True)

            # Breadcrumbs
            breadcrumb_nav = (
                soup.select_one('div.bredcrumbWrap nav.breadcrumbs') or
                soup.select_one('nav.page-width.breadcrumbs')
            )
            breadcrumbs = []
            if breadcrumb_nav:
                for element in breadcrumb_nav.find_all(['a', 'span'], recursive=False):
                    if element.name == 'span' and 'symbol' in element.get('class', []):
                        continue
                    text = element.get_text(strip=True)
                    if text:
                        breadcrumbs.append(text)
            product_data['breadcrumbs'] = " > ".join(breadcrumbs)

            # Prices
            price_div = (
                soup.find('div', id=lambda x: x and x.startswith('pricetemplate')) or
                soup.find('div', class_='psinglePriceWr')
            )
            if price_div:
                sale_price_tag = price_div.select_one('span.psinglePrice.sale .money') or price_div.select_one('span.psinglePrice .money')
                if sale_price_tag:
                    product_data['sale_price'] = sale_price_tag.get_text(strip=True)

                original_price_tag = price_div.select_one('s.psinglePrice .money')
                if original_price_tag:
                    product_data['original_price'] = original_price_tag.get_text(strip=True)

                if not product_data.get('original_price') and product_data.get('sale_price'):
                    product_data['original_price'] = product_data['sale_price']
                    product_data['sale_price'] = None

                discount_percent = price_div.select_one('span.discount-badge .off span')
                if discount_percent:
                    product_data['save_percent'] = discount_percent.get_text(strip=True) + '%'
                else:
                    product_data['save_percent'] = None

            # Images
            image_links = soup.select('a.pr_photo') or soup.select('div.pr_thumbs_item a.gitem-img')
            for a_tag in image_links:
                zoom_src = a_tag.get('data-zoom') or a_tag.get('href')
                if zoom_src:
                    full_url = urljoin('https:', zoom_src)
                    if full_url not in product_data['images']:
                        product_data['images'].append(full_url)

            # Stock
            stock_element = soup.select_one('div.product-stock span.stockLbl') or soup.select_one('span.stockLbl.instock')
            if stock_element:
                product_data['stock'] = stock_element.get_text(strip=True)

            # Product Policies
            policy_div = soup.select_one('div.product__policies.rte') or soup.select_one('p.shippingMsg.mb25')
            if policy_div:
                for br in policy_div.find_all('br'):
                    br.replace_with('\n')
                policy_text = policy_div.get_text(separator=' ', strip=True)
                product_data['product__policies'] = policy_text

            # Description
            desc_div = soup.select_one('div.product-single__description.rte')
            if desc_div:
                for br in desc_div.find_all('br'):
                    br.replace_with('\n')
                raw_text = desc_div.get_text(separator='\n')
                lines = [line.strip() for line in raw_text.split('\n') if line.strip()]
                description_text = '\n'.join(lines)
                product_data['description']['full_description'] = description_text

                        # Size Availability
                size_inputs = soup.find_all("input", {"name": "size"})
                size_info_list = []

                for input_tag in size_inputs:
                    size = input_tag["value"]
                    variant_id = input_tag.get("data-variant-id")

                    if variant_id:
                        variant_url = f"{product_link}?variant={variant_id}"
                        variant_response = requests.get(variant_url)
                        variant_soup = BeautifulSoup(variant_response.text, 'html.parser')

                        add_to_cart_button = variant_soup.find("button", {"id": "AddToCart-template--16869896716541__product"})
                        if add_to_cart_button:
                            is_disabled = add_to_cart_button.has_attr("disabled")
                            status = "Unavailable" if is_disabled else "Available"
                        else:
                            status = "Unknown"

                        size_info_list.append({
                            "size": size,
                            "status": status
                        })

                product_data['variants'] = size_info_list

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
