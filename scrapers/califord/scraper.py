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
from utils.LoggerConstants import CALIFORD_LOGGER
from urllib.parse import urljoin, urlparse
import time


class CalifordScrapper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://califord.com.pk/",
            logger_name=CALIFORD_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "califord"
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

            try:
                product_name_div = soup.find('div', class_='product-info__block-item', attrs={'data-block-id': 'title', 'data-block-type': 'title'})
                if product_name_div:
                    product_title_tag = product_name_div.find('h1', class_='product-title h3')
                    if product_title_tag and product_title_tag.get_text(strip=True):
                        product_data["title"] = product_title_tag.get_text(strip=True)
                    else:
                        product_data["title"] = None
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None


            try:
                breadcrumbs = []
                breadcrumb_container = soup.find('div', class_='container')
                if breadcrumb_container:
                    ul_tag = breadcrumb_container.find('ul')
                    if ul_tag:
                        li_tags = ul_tag.find_all('li')
                        for li in li_tags:
                            a_tag = li.find('a')
                            if a_tag:
                                crumb = a_tag.get_text(strip=True)
                                breadcrumbs.append(crumb)
                            else:
                                strong_tag = li.find('strong')
                                if strong_tag:
                                    crumb = strong_tag.get_text(strip=True)
                                    breadcrumbs.append(crumb)
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []


            try:
                description_text = ""

                # Find the div with class 'accordion__content prose' directly
                accordion_content = soup.find('div', class_='accordion__content prose')
                if accordion_content:
                    # Extract text from the first <p> tag
                    p_tag = accordion_content.find('p')
                    if p_tag:
                        description_text = p_tag.get_text(separator=" ", strip=True)

                    # Extract all bullet points in <li> tags
                    li_tags = accordion_content.find_all('li')
                    bullet_points = [li.get_text(separator=" ", strip=True) for li in li_tags]

                    # Append bullet points to description text (optional)
                    if bullet_points:
                        description_text += "\nBullet Points:\n" + "\n".join(f"- {point}" for point in bullet_points)

                product_data['description'] = description_text
                

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""



            try:
                # Find the <price-list> tag
                price_list = soup.find('price-list', class_='price-list price-list--product')

                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price = re.sub(r'[^\d.]', '', text)
                    return price, currency

                if price_list:
                    sale_price_tag = price_list.find('sale-price')
                    if sale_price_tag:
                        # Extract text after the <span class="sr-only"> tag
                        price_text = sale_price_tag.get_text(strip=True)
                        # Remove 'Sale price' label if included
                        price_text = price_text.replace('Sale price', '').strip()
                        price, currency = extract_price(price_text)
                        product_data['original_price'] = price
                        product_data['sale_price'] = None
                        product_data['currency'] = currency
                    else:
                        # If no <sale-price>, set price as None
                        product_data['original_price'] = None
                        product_data['sale_price'] = None
                        product_data['currency'] = None
                else:
                    product_data['original_price'] = None
                    product_data['sale_price'] = None
                    product_data['currency'] = None

            except Exception as e:
                print(f"Error extracting price data: {e}")


            try:
                breadcrumbs_div = soup.find('div', class_='breadcrumbs')
                categories = []
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
                product_data["category"] = []

            
            
            variants = []
            try:
                sizes = []
                size_fieldset = soup.find('fieldset', class_='variant-picker__option v-stack gap-2')
                if size_fieldset:
                    input_tags = size_fieldset.find_all('input', {'type': 'radio'})
                    for input_tag in input_tags:
                        input_id = input_tag.get('id', '').strip()
                        if input_id:
                            # Find the corresponding label by 'for' attribute
                            label_tag = size_fieldset.find('label', {'for': input_id})
                            if label_tag:
                                size_span = label_tag.find('span')
                                size_text = size_span.get_text(strip=True) if size_span else ''
                                
                                # Check if label has 'is-disabled' class to determine availability
                                label_classes = label_tag.get('class', [])
                                is_disabled = 'is-disabled' in label_classes
                                availability = 'unavailable' if is_disabled else 'available'
                                
                                sizes.append({
                                    'size': size_text,
                                    'availability': availability
                                })
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping sizes: {e}")

            colors = [{'availability': 'available'}]

            for size in sizes:
                combined_availability = 'false' if size['availability'] == 'unavailable' else 'true'
                variants.append({
                    'size': size['size'],
                    'availability': combined_availability
                })

            product_data['variants'] = variants


            try:
                product_images = []

                # Find all divs containing product images
                image_divs = soup.find_all('div', class_='product-gallery__media')

                for div in image_divs:
                    img_tag = div.find('img')
                    if img_tag:
                        src = img_tag.get('src')
                        if src:
                            # Ensure the URL is complete with https:
                            full_url = src if src.startswith('http') else 'https:' + src
                            product_images.append(full_url)

                product_data['images'] = list(set(product_images))  # Remove duplicates if any
                

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []

                try:
                    description_text = ""

                    # Find the <details> tag with class 'accordion__disclosure group'
                    details_tag = soup.find('details', class_='accordion__disclosure group')
                    if details_tag:
                        # Within it, find the <div> with class 'accordion__content prose'
                        content_div = details_tag.find('div', class_='accordion__content prose')
                        if content_div:
                            desc_parts = []

                            # Extract <p> tag text
                            p_tags = content_div.find_all('p')
                            for p in p_tags:
                                desc_parts.append(p.get_text(separator=" ", strip=True))

                            # Extract <ul> list items if present
                            ul_tags = content_div.find_all('ul')
                            for ul in ul_tags:
                                li_items = ul.find_all('li')
                                for li in li_items:
                                    desc_parts.append(li.get_text(separator=" ", strip=True))

                            # Join all parts into final description text
                            description_text = " ".join(desc_parts).strip()

                    product_data['description'] = description_text
                    

                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping description: {e}")
                    product_data['description'] = ""



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

                # Select <a> tags with class 'product-card__media' as per provided tag
                product_links = soup.select('a.product-card__media')

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

                # Pagination: look for next page link (update selector as per actual site pagination class)
                next_page_link = soup.select_one('a.next')
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
