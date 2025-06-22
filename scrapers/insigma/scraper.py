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


class insigma_scraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://insignia.com.pk/",
            logger_name=INSIGMA_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "Ingsigma"
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

        # Initialize product data with all fields
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
            'attributes': {
                'breadcrumbs': []
            },
            'raw_data': {},
        }

        try:
            response = await self.async_make_request(product_link)
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                h1_tag = soup.select_one('h1')
                if h1_tag:
                    product_data['title'] = h1_tag.get_text(strip=True)
                    self.log_debug(f"Product title extracted: {product_data['title']}")
                else:
                    product_data['title'] = None
                    self.log_debug("No <h1> tag found for product title.")
            except Exception as e:
                self.log_debug(f"Exception while extracting product title: {e}")
                product_data['title'] = None

            try:
                sku_element = soup.select_one('span.variant-sku')
                if sku_element:
                    product_data['sku'] = sku_element.get_text(strip=True)
                    self.log_debug(f"SKU extracted: {product_data['sku']}")
                else:
                    product_data['sku'] = None
                    self.log_debug("No <span class='variant-sku'> found for SKU.")
            except Exception as e:
                self.log_debug(f"Exception while extracting SKU: {e}")
                product_data['sku'] = None

            try:
                breadcrumb_div = soup.find('div', class_='breadcrumb')
                if breadcrumb_div:
                    links = breadcrumb_div.find_all('a')
                    if len(links) >= 2:
                        second_link = links[1]
                        product_data['category'] = second_link.get_text(strip=True)
                        self.log_debug(f"Category extracted: {product_data['category']}")
                    else:
                        product_data['category'] = None
                        self.log_debug("Breadcrumb found, but not enough <a> tags to extract category.")
                else:
                    product_data['category'] = None
                    self.log_debug("No <div class='breadcrumb'> found.")
            except Exception as e:
                self.log_debug(f"Exception while extracting category from breadcrumb: {e}")
                product_data['category'] = None

            try:
                original_price_tag = soup.find('s', class_='price-item--regular')
                sale_price_tag = soup.find('span', class_='price-item--sale')
                sale_percent_tag = soup.find('p', class_='save-percentage price__badge-sale')

                currency = None

                def clean_price(price_str):
                    cleaned = re.sub(r'(PKR|Rs|₨|\$|€|£|¥|USD|EUR|GBP|JPY|₹)', '', price_str)
                    return cleaned.replace('\xa0', ' ').strip()

                if original_price_tag:
                    original_text = original_price_tag.get_text()
                    product_data['original_price'] = clean_price(original_text)
                    self.log_debug(f"Original price extracted: {product_data['original_price']}")

                    currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', original_text)
                    if currency_match:
                        currency = currency_match.group(0)
                        self.log_debug(f"Currency extracted from original price: {currency}")

                    if sale_price_tag:
                        sale_text = sale_price_tag.get_text()
                        product_data['sale_price'] = clean_price(sale_text)
                        self.log_debug(f"Sale price extracted: {product_data['sale_price']}")

                        if not currency:
                            currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', sale_text)
                            if currency_match:
                                currency = currency_match.group(0)
                                self.log_debug(f"Currency extracted from sale price: {currency}")
                else:
                    regular_price_tag = soup.find('span', class_='price-item--regular')
                    if regular_price_tag:
                        regular_text = regular_price_tag.get_text()
                        product_data['original_price'] = clean_price(regular_text)
                        self.log_debug(f"Regular price extracted (no <s> tag): {product_data['original_price']}")

                        currency_match = re.search(r'[₹Rs₨$€£¥]+|PKR|USD|EUR|GBP|JPY', regular_text)
                        if currency_match:
                            currency = currency_match.group(0)
                            self.log_debug(f"Currency extracted from regular price: {currency}")

                if sale_percent_tag:
                    product_data['sale_percentage'] = sale_percent_tag.get_text(strip=True)
                    self.log_debug(f"Sale percentage extracted: {product_data['sale_percentage']}")

                if currency:
                    product_data['currency'] = currency
            except Exception as e:
                self.log_debug(f"Exception while extracting price information: {e}")
                product_data['original_price'] = None
                product_data['sale_price'] = None
                product_data['sale_percentage'] = None
                product_data['currency'] = None

            try:
                product_data['attributes'] = {}
                breadcrumb_div = soup.find('div', class_='breadcrumb')
                if breadcrumb_div:
                    breadcrumb_texts = []
                    for node in breadcrumb_div.find_all(['a', 'span']):
                        text = node.get_text(strip=True)
                        if text and text != '>':
                            breadcrumb_texts.append(text)

                    if breadcrumb_texts:
                        product_data['attributes']['breadcrumbs'] = breadcrumb_texts
                        self.log_debug(f"Breadcrumbs extracted: {breadcrumb_texts}")
                    else:
                        self.log_debug("Breadcrumb <div> found but no meaningful text extracted.")
                else:
                    self.log_debug("No <div class='breadcrumb'> found.")
            except Exception as e:
                self.log_debug(f"Exception while extracting breadcrumbs: {e}")
                product_data['attributes']['breadcrumbs'] = []

            try:
                description_section = soup.find('div', class_='product__description rte quick-add-hidden')
                if description_section:
                    paragraphs = description_section.find_all('p')
                    description = '\n'.join(p.get_text(strip=True) for p in paragraphs)
                    product_data['description'] = description
                    self.log_debug(f"Description extracted: {description[:60]}...")
                else:
                    product_data['description'] = None
                    self.log_debug("No product description section found.")
            except Exception as e:
                self.log_debug(f"Exception while extracting product description: {e}")
                product_data['description'] = None

            try:
                product_images = set()

                def add_image_url(url):
                    if url:
                        if url.startswith('//'):
                            url = 'https:' + url
                        product_images.add(url)

                try:
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
                    self.log_debug("Main product images extracted successfully.")
                except Exception as e:
                    self.log_debug(f"Error extracting main product images: {e}")

                base_url = "https://insignia.com.pk"
                color_links = soup.select('fieldset.option_color a[href]')
                for a in color_links:
                    color_href = a['href']
                    color_url = base_url + color_href
                    try:
                        response = await self.async_make_request(color_url)
                        color_html = response.text
                        color_soup = BeautifulSoup(color_html, 'html.parser')

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
                        self.log_debug(f"Images extracted from color variant: {color_url}")
                    except Exception as e:
                        self.log_debug(f"Error loading images for color variant: {color_url} -> {str(e)}")

                product_data['images'] = list(product_images)
                self.log_debug(f"Total images collected: {len(product_data['images'])}")
            except Exception as e:
                self.log_debug(f"General exception in image extraction: {e}")
                product_data['images'] = []

            try:
                product_data['variants'] = []

                current_color_element = soup.select_one('.option_color strong.active__value')
                current_color = current_color_element.text.strip() if current_color_element else "N/A"

                is_available = soup.select_one('.product-form__submit')
                base_available = bool(is_available and 'Add to cart' in is_available.text.strip())

                all_size_elements = soup.select('fieldset.option_size input[type="radio"]')

                if all_size_elements:
                    for size_input in all_size_elements:
                        size_value = size_input.get('value')
                        if not size_value:
                            continue
                        is_disabled = 'disabled' in size_input.get('class', [])
                        availability = bool(not is_disabled and base_available)
                        product_data['variants'].append({
                            'color': current_color,
                            'size': size_value,
                            'availability': availability
                        })
                else:
                    product_data['variants'].append({
                        'color': current_color,
                        'size': None,
                        'availability': base_available
                    })

                self.log_debug(f"Variants for current color '{current_color}' extracted successfully.")

                other_color_links = soup.select('fieldset.option_color a[data-color][href]')
                other_colors = {
                    link.get('data-color').strip(): link.get('href')
                    for link in other_color_links
                    if link.get('data-color') and link.get('href') and link.get('data-color').strip() != current_color
                }

                for color_name, color_url in other_colors.items():
                    try:
                        full_url = 'https://insignia.com.pk' + color_url if not color_url.startswith('http') else color_url
                        response = await self.async_make_request(full_url)
                        color_html = response.text
                        color_soup = BeautifulSoup(color_html, 'html.parser')

                        color_available = color_soup.select_one('.product-form__submit')
                        color_base_available = bool(color_available and 'Add to cart' in color_available.text.strip())

                        size_inputs = color_soup.select('fieldset.option_size input[type="radio"]')
                        if size_inputs:
                            for size_input in size_inputs:
                                size_value = size_input.get('value')
                                if not size_value:
                                    continue
                                is_disabled = 'disabled' in size_input.get('class', [])
                                availability = bool(not is_disabled and color_base_available)
                                product_data['variants'].append({
                                    'color': color_name,
                                    'size': size_value,
                                    'availability': availability
                                })
                        else:
                            product_data['variants'].append({
                                'color': color_name,
                                'size': None,
                                'availability': color_base_available
                            })

                        self.log_debug(f"Variants for color '{color_name}' extracted successfully.")
                    except Exception as e:
                        self.log_debug(f"Error loading color variant {color_url}: {str(e)}")
                        continue
            except Exception as e:
                self.log_debug(f"General exception in variant extraction: {e}")
                product_data['variants'] = []


        except Exception as e:
            self.log_debug(f"Error scraping PDP {product_link}: {str(e)}")

        return product_data

        
    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        current_url = url

        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(current_url)

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
