import os
import re
import json
import asyncio
import aiohttp
import requests
from bs4 import BeautifulSoup
from typing import List, Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import CHANGE_LOGGER
from urllib.parse import urljoin, urlparse
import time


class ChangeClothingsScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://changeclothings.com.pk/",
            logger_name=CHANGE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "changeclothings"
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
            'raw_data': {}
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            # TITLE
            try:
                product_name_div = soup.find('div', class_='product__title')
                if product_name_div:
                    product_title_tag = product_name_div.find('h1') or product_name_div.find('h2', class_='h1')
                    if product_title_tag:
                        product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")


            # SKU
            try:
                sku = None
                for p_tag in soup.find_all('p'):
                    if 'SKU:' in p_tag.get_text():
                        text = p_tag.get_text(strip=True)
                        sku = text.split('SKU:')[-1].strip()
                        break
                product_data['sku'] = sku
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping SKU: {e}")

            # IMAGES
            try:
                image_urls = []
                image_divs = soup.find_all("div", class_="product__media")
                for div in image_divs:
                    img_tag = div.find("img")
                    if img_tag and img_tag.get("src"):
                        src = img_tag["src"]
                        full_url = "https:" + src.split("?")[0]
                        image_urls.append(full_url)
                product_data['images'] = list(set(image_urls))
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")

            # PRICE
            try:
                price_container = soup.find('div', class_='price__container')

                def clean_price(p):
                    if p:
                        p = re.sub(r'(PKR|Rs\.?|,)', '', p, flags=re.IGNORECASE).strip()
                        p = re.sub(r'[^\d.]', '', p)
                        if p:
                            p = f"{float(p):,.2f}"
                    return p

                original_price = None
                sale_price = None

                if price_container:
                    original_tag = price_container.find("s", class_="price-item--regular")
                    sale_tag = price_container.find("span", class_="price-item--sale")

                    if original_tag:
                        original_text = original_tag.get_text(strip=True)
                        original_price = clean_price(original_text)

                    if sale_tag:
                        sale_text = sale_tag.get_text(strip=True)
                        sale_price = clean_price(sale_text)

                    if not original_price and sale_price:
                        original_price = sale_price
                        sale_price = None

                    if original_price and sale_price and original_price == sale_price:
                        sale_price = None

                    container_text = price_container.get_text()
                    currency_match = re.search(r'[₨$€£]', container_text)
                    currency_symbol = currency_match.group() if currency_match else None

                    product_data['original_price'] = original_price
                    product_data['sale_price'] = sale_price
                    product_data['currency'] = currency_symbol
            except Exception as e:
                self.log_debug(f"Error extracting price data: {e}")

            # CATEGORY
            try:
                categories = []
                breadcrumbs_div = soup.find('div', class_='breadcrumbs')
                if breadcrumbs_div:
                    ul = breadcrumbs_div.find('ul')
                    if ul:
                        li_tags = ul.find_all('li')
                        for li in li_tags:
                            if 'home' in li.get('class', []):
                                continue
                            a_tag = li.find('a')
                            if a_tag:
                                categories.append(a_tag.get_text(strip=True))
                            else:
                                strong_tag = li.find('strong')
                                if strong_tag:
                                    categories.append(strong_tag.get_text(strip=True))
                product_data["category"] = categories
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping categories from breadcrumbs: {e}")

            # DESCRIPTION
            try:
                description_div = soup.find("div", class_="product__description")
                if description_div:
                    full_text = ""
                    skip_keywords = ["SKU", "Care Instructions"]
                    for element in description_div.find_all(['p', 'ul']):
                        if any(keyword in element.text for keyword in skip_keywords):
                            continue
                        full_text += element.get_text(separator=" ", strip=True) + " "
                    product_data['description'] = full_text.strip()
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")

            # RAW_NOTE
            try:
                raw_note = None
                description_div = soup.find("div", class_="product__description")
                if description_div:
                    for p_tag in description_div.find_all("p"):
                        strong_tag = p_tag.find("strong")
                        if strong_tag and "Note:" in strong_tag.text:
                            raw_note = p_tag.get_text(strip=True)
                            break
                product_data["raw_data"]["note"] = raw_note
            except Exception as e:
                self.log_debug(f"Exception occurred while extracting raw note: {e}")

            # AVAILABILITY
            try:
                sold_out_tag = soup.find("span", class_="badge price__badge-sold-out color-scheme-3")
                product_data['availability'] = False if sold_out_tag else True
            except Exception as e:
                self.log_debug(f"Exception occurred while checking availability: {e}")

            # VARIANTS
            try:
                variants = []
                size_fieldset = soup.find('fieldset', class_='product-form__input--pill')
                color_fieldset = soup.find('fieldset', class_='product-form__input--swatch')

                sizes = []
                colors = []

                if size_fieldset:
                    input_tags = size_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in input_tags:
                        size_value = input_tag.get('value', '').strip()
                        if size_value:
                            is_disabled = input_tag.has_attr('disabled') or 'disabled' in input_tag.get('class', [])
                            availability = 'false' if is_disabled else 'true'
                            sizes.append({'size': size_value, 'availability': availability})

                if color_fieldset:
                    input_tags = color_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in input_tags:
                        color_value = input_tag.get('value', '').strip()
                        if color_value:
                            is_disabled = input_tag.has_attr('disabled') or 'disabled' in input_tag.get('class', [])
                            availability = 'false' if is_disabled else 'true'
                            colors.append({'color': color_value, 'availability': availability})

                if sizes and colors:
                    for size in sizes:
                        for color in colors:
                            availability = 'true' if size['availability'] == 'true' and color['availability'] == 'true' else 'false'
                            variants.append({
                                'size': size['size'],
                                'color': color['color'],
                                'availability': availability
                            })
                elif sizes:
                    for size in sizes:
                        variants.append({
                            'size': size['size'],
                            'color': None,
                            'availability': size['availability']
                        })
                elif colors:
                    for color in colors:
                        variants.append({
                            'size': None,
                            'color': color['color'],
                            'availability': color['availability']
                        })

                product_data['variants'] = variants
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping variants: {e}")

        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data



    async def scrape_products_links(self, url):
        from urllib.parse import urljoin

        all_product_links = []
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping: {current_url}")
                response = await self.async_make_request(current_url)
                soup = BeautifulSoup(response.text, 'html.parser')

                # Select <a> tags with class 'full-unstyled-link'
                product_links = soup.select('a.full-unstyled-link')

                if not product_links:
                    self.log_info("No product links found on this page. Stopping.")
                    break

                # Extract and add product URLs
                for link_tag in product_links:
                    href = link_tag.get('href')
                    if href:
                        product_url = urljoin(self.base_url, href)
                        if product_url not in all_product_links:
                            all_product_links.append(product_url)

                self.log_info(f"Collected {len(all_product_links)} product links so far.")

                # Pagination: look for next page link
                next_page_link = soup.select_one('a.next')  # Adjust selector based on actual site pagination class
                if next_page_link:
                    next_href = next_page_link.get('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                        continue
                    else:
                        self.log_info("Next page href not found. Stopping pagination.")
                        break
                else:
                    self.log_info("No next page link found. Finished scraping all pages.")
                    break

            except Exception as e:
                self.log_error(f"Error scraping {current_url}: {e}")
                break

        self.log_info(f"Total collected {len(all_product_links)} product links.")
        return all_product_links


         
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
