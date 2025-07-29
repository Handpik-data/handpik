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
from utils.LoggerConstants import HUNZACANDLES_LOGGER
from urllib.parse import urljoin, urlparse
import time


class HunzaCandlesScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://hunzacandle.com/",
            logger_name=HUNZACANDLES_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "HunzaCandles"
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

            # --------------------- Title ---------------------
            try:
                product_title_tag = soup.find('h1', class_='productView-title')
                if product_title_tag:
                    span_tag = product_title_tag.find('span')
                    if span_tag and span_tag.get_text(strip=True):
                        product_data["title"] = span_tag.get_text(strip=True)
                    else:
                        product_data["title"] = product_title_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception scraping title: {e}")

         



             # --------------------- Prices ---------------------
            try:
                price_container = soup.find('div', class_='productView-price')
                if price_container:
                    # Extract original price
                    original_tag = price_container.find('span', class_='price-item price-item--regular')
                    if original_tag:
                        original_text = original_tag.get_text(strip=True)
                        match = re.match(r"([^\d]+)([\d,]+\.\d+)", original_text)
                        if match:
                            product_data["currency"] = match.group(1).strip()
                            product_data["original_price"] = match.group(2).strip()

                    # Extract sale price
                    sale_tag = price_container.find('span', class_='price-item price-item--sale')
                    if sale_tag:
                        sale_text = sale_tag.get_text(strip=True)
                        sale_match = re.match(r"[^\d]+([\d,]+\.\d+)", sale_text)
                        if sale_match:
                            sale_price_value = sale_match.group(1).strip()
                            # Set sale price only if different from original
                            if sale_price_value != product_data["original_price"]:
                                product_data["sale_price"] = sale_price_value
                            else:
                                product_data["sale_price"] = None
                        else:
                            product_data["sale_price"] = None
                    else:
                        product_data["sale_price"] = None
            except Exception as e:
                self.log_debug(f"Exception scraping prices: {e}")


            try:
                details_container = soup.find('div', class_='toggle-content', id='tab-product-details-mobile')
                if details_container:
                    details_lines = []
                    for b_tag in details_container.find_all('b'):
                        key = b_tag.get_text(strip=True).rstrip(':')
                        value = ""
                        if b_tag.next_sibling:
                            value = b_tag.next_sibling.strip()
                        ul_tag = b_tag.find_next_sibling('ul')
                        if ul_tag:
                            li_texts = [li.get_text(strip=True) for li in ul_tag.find_all('li') if li.get_text(strip=True)]
                            if li_texts:
                                if value:
                                    value += "\\n" + "\\n".join(li_texts)
                                else:
                                    value = "\\n".join(li_texts)
                        if key:
                            if value:
                                details_lines.append(f"{key}: {value}")
                            else:
                                details_lines.append(f"{key}:")
                    if details_lines:
                        product_data['attributes']['product_details'] = "\\n".join(details_lines)
            except Exception as e:
                self.log_debug(f"Exception scraping product details: {e}")


                                  # --------------------- Breadcrumbs ---------------------
            try:
                breadcrumbs = []
                breadcrumb_container = soup.find('nav', class_='breadcrumb')
                if breadcrumb_container:
                    a_tags = breadcrumb_container.find_all('a')
                    breadcrumbs.extend(a_tag.get_text(strip=True) for a_tag in a_tags)
                    span_tags = breadcrumb_container.find_all('span')
                    for span_tag in span_tags:
                        if "separate" not in span_tag.get("class", []) and "observe-element" not in span_tag.get("class", []):
                            text = span_tag.get_text(strip=True)
                            if text:
                                breadcrumbs.append(text)
                product_data['attributes']['breadcrumbs'] = breadcrumbs
            except Exception as e:
                self.log_debug(f"Exception scraping breadcrumbs: {e}")


                   # --------------------- Categories ---------------------
            try:
                categories = []
                breadcrumb_container = soup.find('nav', class_='breadcrumb')
                if breadcrumb_container:
                    a_tags = breadcrumb_container.find_all('a')
                    categories.extend(a_tag.get_text(strip=True) for a_tag in a_tags if a_tag.get_text(strip=True).lower() != 'home')
                    span_tags = breadcrumb_container.find_all('span')
                    for span_tag in span_tags:
                        if "separate" not in span_tag.get("class", []) and "observe-element" not in span_tag.get("class", []):
                            text = span_tag.get_text(strip=True)
                            if text:
                                categories.append(text)
                product_data["category"] = categories
            except Exception as e:
                self.log_debug(f"Exception scraping categories: {e}")


                        # --------------------- Images ---------------------
            try:
                images = []
                # Find all divs with class 'media'
                image_containers = soup.find_all('div', class_='media')
                for container in image_containers:
                    img_tag = container.find('img')
                    if img_tag:
                        src = img_tag.get('src')
                        if src:
                            # Convert relative URL to full URL
                            if src.startswith("//"):
                                src = "https:" + src
                            images.append(src)
                product_data['images'] = images
            except Exception as e:
                self.log_debug(f"Exception scraping images: {e}")
                product_data['images'] = []


       

            # --------------------- Description ---------------------
            try:
                desc_div = soup.find('div', class_='toggle-content', id='tab-about-the-fragrance-mobile')
                description_text = ""
                if desc_div:
                    content_lines = []
                    for child in desc_div.children:
                        if isinstance(child, str):
                            text = child.strip()
                            if text:
                                content_lines.append(text)
                        elif child.name == 'b':
                            b_text = child.get_text(strip=True)
                            if b_text:
                                content_lines.append(b_text)
                        elif child.name == 'p':
                            for subchild in child.children:
                                if subchild.name == 'b':
                                    note_type = subchild.get_text(strip=True).rstrip(':')
                                    note_value = subchild.next_sibling.strip() if subchild.next_sibling else ""
                                    content_lines.append(f"{note_type}: {note_value}")
                                elif isinstance(subchild, str):
                                    sub_text = subchild.strip()
                                    if sub_text:
                                        content_lines.append(sub_text)
                    description_text = "\\n".join(content_lines)
                product_data['description'] = description_text
            except Exception as e:
                self.log_debug(f"Exception scraping description: {e}")
                product_data['description'] = ""

            # --------------------- Reviews ---------------------
            try:
                reviews_combined = []
                review_divs = soup.find_all('div', class_='jdgm-rev')
                for review in review_divs:
                    content_lines = []
                    author_tag = review.find('span', class_='jdgm-rev__author')
                    author = author_tag.get_text(strip=True) if author_tag else ""
                    content_lines.append(f"Author: {author}")
                    rating_tag = review.find('span', class_='jdgm-rev__rating')
                    rating = rating_tag['data-score'] if rating_tag and rating_tag.has_attr('data-score') else ""
                    content_lines.append(f"Rating: {rating}")
                    date_tag = review.find('span', class_='jdgm-rev__timestamp')
                    date = date_tag.get_text(strip=True) if date_tag else ""
                    content_lines.append(f"Date: {date}")
                    body_tag = review.find('div', class_='jdgm-rev__body')
                    review_text = ""
                    if body_tag:
                        p_tag = body_tag.find('p')
                        review_text = p_tag.get_text(strip=True) if p_tag else ""
                    content_lines.append(f"Review: {review_text}")
                    review_line = "\\n".join(content_lines)
                    reviews_combined.append(review_line)
                all_reviews_text = "\\n".join(reviews_combined)
                product_data['raw_data']['reviews'] = all_reviews_text
            except Exception as e:
                self.log_debug(f"Exception scraping reviews: {e}")
                product_data['raw_data']['reviews'] = ""

            # --------------------- Disclaimer ---------------------
            try:
                disclaimer = ""
                toggle_content = soup.find('div', class_='toggle-content', id='tab-disclaimer-mobile')
                if toggle_content:
                    content_lines = []
                    for child in toggle_content.children:
                        if child.name == 'b':
                            text = child.get_text(strip=True)
                            if text:
                                content_lines.append(text)
                        elif isinstance(child, str):
                            text = child.strip()
                            if text:
                                content_lines.append(text)
                    disclaimer = "\\n".join(content_lines)
                product_data['raw_data']['disclaimer'] = disclaimer
            except Exception as e:
                self.log_debug(f"Exception scraping disclaimer: {e}")
                product_data['raw_data']['disclaimer'] = ""

            # --------------------- How To Use ---------------------
            try:
                how_to_use = ""
                toggle_content = soup.find('div', class_='toggle-content', id='tab-how-to-use-mobile')
                if toggle_content:
                    content_lines = []
                    for child in toggle_content.children:
                        if child.name in ['b', 'h3', 'h4']:
                            text = child.get_text(strip=True)
                            if text:
                                content_lines.append(text)
                        elif child.name == 'p':
                            for subchild in child.children:
                                if subchild.name == 'b':
                                    sub_text = subchild.get_text(strip=True)
                                    if sub_text:
                                        content_lines.append(sub_text)
                                elif isinstance(subchild, str):
                                    sub_text = subchild.strip()
                                    if sub_text:
                                        content_lines.append(sub_text)
                        elif isinstance(child, str):
                            text = child.strip()
                            if text:
                                content_lines.append(text)
                    how_to_use = "\\n".join(content_lines)
                product_data['raw_data']['how_to_use'] = how_to_use
            except Exception as e:
                self.log_debug(f"Exception scraping how to use: {e}")
                product_data['raw_data']['how_to_use'] = ""

            # --------------------- Return & Exchange Policy ---------------------
            try:
                return_policy = ""
                toggle_content = soup.find('div', class_='toggle-content', id='tab-shipping-amp-exchange-mobile')
                if toggle_content:
                    content_lines = []
                    h4_tags = toggle_content.find_all('h4')
                    for h4 in h4_tags:
                        if 'Return & Exchange Policy' in h4.get_text(strip=True):
                            content_lines.append(h4.get_text(strip=True))
                            p_tag = h4.find_next_sibling('p')
                            if p_tag:
                                policy_text = p_tag.get_text(separator="\\n", strip=True)
                                content_lines.append(policy_text)
                            break
                    return_policy = "\\n".join(content_lines)
                product_data['raw_data']['return_and_exchange_policy'] = return_policy
            except Exception as e:
                self.log_debug(f"Exception scraping return & exchange policy: {e}")
                product_data['raw_data']['return_and_exchange_policy'] = ""

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

                # Updated selector to match <a class="card-link">
                product_links = soup.select('a.card-link')

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

                # Pagination: look for next page link (adjust selector based on site)
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
