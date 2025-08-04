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
from utils.LoggerConstants import OUTFITTERS_LOGGER
from urllib.parse import urljoin, urlparse
import time


class OutfiterScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=1):
        super().__init__(
            base_url="https://outfitters.com.pk/",
            logger_name=OUTFITTERS_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "outfitters"
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
                product_name_div = soup.find('div', class_='product__title')
                if product_name_div:
                    # First try to get text from <h1>
                    product_title_tag = product_name_div.find('h1')
                    if product_title_tag and product_title_tag.get_text(strip=True):
                        product_data["title"] = product_title_tag.get_text(strip=True)
                    else:
                        # If <h1> not found, try <h2> inside <a> tag
                        a_tag = product_name_div.find('a', class_='product__title')
                        if a_tag:
                            h2_tag = a_tag.find('h2', class_='h1')
                            if h2_tag and h2_tag.get_text(strip=True):
                                product_data["title"] = h2_tag.get_text(strip=True)
                            else:
                                product_data["title"] = None
                        else:
                            product_data["title"] = None
                else:
                    product_data["title"] = None
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product's title: {e}")
                product_data["title"] = None


                try:
                    fit_description = ""
                    composition_care = []

                    # Find the modal body container
                    modal_body = soup.find('div', class_='modal-body product-popup-modal__content-info')
                    if modal_body:
                        # Extract FIT description
                        p_tags = modal_body.find_all('p')
                        for p in p_tags:
                            strong_tag = p.find('strong')
                            if strong_tag and 'FIT' in strong_tag.get_text(strip=True).upper():
                                # Get the next <p> after FIT for description
                                next_index = p_tags.index(p) + 1
                                if next_index < len(p_tags):
                                    fit_description = p_tags[next_index].get_text(strip=True)
                                break

                        # Extract Composition & Care section
                        ul_tag = modal_body.find('ul')
                        if ul_tag:
                            li_tags = ul_tag.find_all('li')
                            for li in li_tags:
                                item = li.get_text(strip=True)
                                composition_care.append(item)

                    # Save into product_data['attributes']
                    product_data['attributes']['fit_description'] = fit_description
                    product_data['attributes']['composition_and_care'] = composition_care

                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping fit and composition/care: {e}")
                    product_data['attributes']['fit_description'] = ""
                    product_data['attributes']['composition_and_care'] = []


                try:
                    deliveries_and_returns = {
                        'deliveries': [],
                        'returns': []
                    }

                    # Find the modal body container
                    modal_body = soup.find('div', class_='modal-body product-popup-modal__content-info')
                    if modal_body:
                        # Extract Deliveries section
                        deliveries_div = modal_body.find('div', class_='domestic')
                        if deliveries_div:
                            delivery_p_tags = deliveries_div.find_all('p')
                            for p in delivery_p_tags:
                                text = p.get_text(strip=True)
                                if text:
                                    deliveries_and_returns['deliveries'].append(text)

                        # Extract Returns section
                        # Find the <p> with RETURNS heading
                        returns_heading = modal_body.find('p', class_='modal-body-head', text=lambda x: x and 'RETURNS' in x.upper())
                        if returns_heading:
                            # Extract all subsequent <p> tags after RETURNS heading
                            p_tags = returns_heading.find_all_next('p')
                            for p in p_tags:
                                # Stop if a new heading is encountered
                                if p.get('class') == ['modal-body-head']:
                                    break
                                text = p.get_text(strip=True)
                                if text:
                                    deliveries_and_returns['returns'].append(text)

                    # Save into product_data['raw_data']
                    product_data['raw_data']['deliveries_and_returns'] = deliveries_and_returns

                except Exception as e:
                    self.log_debug(f"Exception occurred while scraping deliveries and returns: {e}")
                    product_data['raw_data']['deliveries_and_returns'] = {
                        'deliveries': [],
                        'returns': []
                    }



            try:
                care_instructions = ""
                p_tags = soup.find_all('p')
                for p in p_tags:
                    strong_tag = p.find('strong')
                    if strong_tag and 'Care Instructions:' in strong_tag.get_text(strip=True):
                        full_text = p.get_text(separator=" ", strip=True)
                        care_instructions = full_text.replace('Care Instructions:', '').strip()
                        break
                product_data['raw_data']['care_instructions'] = care_instructions
            except Exception as e:
                self.log_debug(f"Exception occurred while scraping care instructions: {e}")
                product_data['raw_data']['care_instructions'] = ""


            try:
                product_images = []

                # Find all img tags with class 'zoomImg' and id starting with 'swiperslide-'
                img_tags = soup.find_all('img', class_='zoomImg', id=lambda x: x and x.startswith('swiperslide-'))

                for img_tag in img_tags:
                    src_img_url = img_tag.get('src')
                    if src_img_url:
                        # Ensure URL is complete with https:
                        if src_img_url.startswith('//'):
                            src_img_url = 'https:' + src_img_url
                        elif src_img_url.startswith('/'):
                            src_img_url = 'https://outfitters.com.pk' + src_img_url

                        product_images.append(src_img_url)

                # Remove duplicates while preserving order
                seen = set()
                unique_images = []
                for img in product_images:
                    if img not in seen:
                        unique_images.append(img)
                        seen.add(img)

                # Save to product_data['images']
                product_data['images'] = unique_images

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping product images: {e}")
                product_data['images'] = []


            try:
                sku_tag = soup.find('p', class_='pro-sku product__text caption-with-letter-spacing desktop')
                if sku_tag:
                    product_data['sku'] = sku_tag.get_text(strip=True)
                else:
                    product_data['sku'] = None
            except Exception as e:
                print(f"Error extracting SKU: {e}")



            # ✅ Updated Price
            try:
                price_container = soup.find('div', class_='price__container')

                def extract_price(text):
                    text = text.replace("From", "").strip()
                    currency_match = re.match(r'^(\D+)', text)
                    currency = currency_match.group(1).strip() if currency_match else None
                    price = re.sub(r'[^\d.]', '', text)
                    return price, currency

                if price_container:
                    original_tag = price_container.select_one('s.price-item--regular .money')
                    sale_tag = price_container.select_one('span.price-item--sale .money')

                    if original_tag and sale_tag:
                        original, currency = extract_price(original_tag.get_text(strip=True))
                        sale, _ = extract_price(sale_tag.get_text(strip=True))

                        if original == sale:
                            product_data['original_price'] = original
                            product_data['sale_price'] = None
                        else:
                            product_data['original_price'] = original
                            product_data['sale_price'] = sale

                        product_data['currency'] = currency

                    elif sale_tag:
                        sale, currency = extract_price(sale_tag.get_text(strip=True))
                        product_data['original_price'] = sale
                        product_data['sale_price'] = None
                        product_data['currency'] = currency

                    else:
                        regular_tag = price_container.select_one('div.price__regular span.price-item--regular .money')
                        if regular_tag:
                            regular, currency = extract_price(regular_tag.get_text(strip=True))
                            product_data['original_price'] = regular
                            product_data['sale_price'] = None
                            product_data['currency'] = currency

            except Exception as e:
                print(f"Error extracting price data: {e}")


            try:
             

                # Extract Product Details & Composition
                details_div = soup.find('div', class_='product__description rte quick-add-hidden')
                if details_div:
                    details_text = details_div.get_text(separator='\n').strip()
                    product_data['attributes']['product_details_and_composition'] = details_text
                else:
                    product_data['attributes']['product_details_and_composition'] = ""

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping SKU and product details/composition: {e}")

                product_data['attributes']['product_details_and_composition'] = ""






            try:
                returns_conditions = []

                # Find the modal body container
                modal_body = soup.find('div', class_='modal-body product-popup-modal__content-info')
                if modal_body:
                    # Extract all <p> tags within this div
                    p_tags = modal_body.find_all('p')
                    for p in p_tags:
                        text = p.get_text(separator=" ", strip=True)
                        if text:
                            returns_conditions.append(text)

                # Save into product_data['raw_data']
                product_data['raw_data']['returns_conditions'] = returns_conditions

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping returns conditions: {e}")
                product_data['raw_data']['returns_conditions'] = []



            except Exception as e:
                print(f"Exception occurred while scraping SKU: {e}")


            try:
                sizes_status = []

                select_tag = soup.find('select', id=lambda x: x and 'Variants' in x)
                if select_tag:
                    options = select_tag.find_all('option')
                    for option in options:
                        text = option.get_text(strip=True)

                        # Extract color and size from text like "Off White / M / HS-25"
                        parts = text.split('/')
                        color = parts[0].strip() if len(parts) > 0 else None
                        size = parts[1].strip() if len(parts) > 1 else None

                        # Check if option is disabled or contains 'Sold out'
                        is_disabled = option.has_attr('disabled')
                        is_sold_out_text = 'sold out' in text.lower()
                        availability = not (is_disabled or is_sold_out_text)

                        sizes_status.append({
                            'color': color,
                            'size': size,
                            'available': availability
                        })

                # Save to product_data['variants']
                product_data['variants'] = sizes_status

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping variants: {e}")
                product_data['variants'] = []


            try:
                description_text = ""

                # Find the span tag with class 'metafield-multi_line_text_field'
                desc_span = soup.find('span', class_='metafield-multi_line_text_field')
                if desc_span:
                    # Extract text with proper line break handling
                    description_text = desc_span.get_text(separator=" ", strip=True)
                else:
                    self.log_debug("Description span with class 'metafield-multi_line_text_field' not found.")

                product_data['description'] = description_text

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping description: {e}")
                product_data['description'] = ""


            # Assuming soup = BeautifulSoup(response.text, 'html.parser') has already been defined

            deliveries_returns = None
            accordion_div = soup.find("div", class_="product__accordion")

            if accordion_div:
                details = accordion_div.find("details")
                if details:
                    accordion_content = details.find("div", class_="accordion__content")
                    if accordion_content:
                        deliveries_returns = accordion_content.get_text(separator="\n", strip=True)

            # Store in product_data['raw_data']
            product_data["raw_data"] = {
                "deliveries_returns": deliveries_returns
            }

            try:
                    product_images = []

                    # Find all img tags with class 'zoomImg' and id starting with 'swiperslide-'
                    img_tags = soup.find_all('img', class_='zoomImg', id=lambda x: x and x.startswith('swiperslide-'))
                    for img_tag in img_tags:
                        src_img_url = img_tag.get('src')
                        if src_img_url:
                            # Ensure URL is complete with https:
                            if src_img_url.startswith('//'):
                                src_img_url = 'https:' + src_img_url
                            elif src_img_url.startswith('/'):
                                src_img_url = 'https://outfitters.com.pk' + src_img_url

                            product_images.append(src_img_url)

                    # Remove duplicates while preserving order
                    seen = set()
                    unique_images = []
                    for img in product_images:
                        if img not in seen:
                            unique_images.append(img)
                            seen.add(img)

                    product_data['images'] = unique_images

            except Exception as e:
                    self.log_debug(f"Exception occurred while scraping product images: {e}")
                    product_data['images'] = []


            try:
                deliveries_returns = None

                # Find all divs with class accordion__content rte
                accordion_divs = soup.find_all("div", class_="accordion__content rte")

                for div in accordion_divs:
                    # Check if the div contains the relevant return keywords
                    if any(keyword in div.get_text(strip=True) for keyword in ["Undergarments", "Jewellery", "Fragrances", "Accessories"]):
                        deliveries_returns = div.get_text(separator="\n", strip=True)
                        break

                # Store in product_data['raw_data']
                product_data.setdefault("raw_data", {})["deliveries_returns"] = deliveries_returns

            except Exception as e:
                self.log_debug(f"Exception occurred while scraping deliveries_returns: {e}")
                product_data.setdefault("raw_data", {})["deliveries_returns"] = None

              


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

                # Select <a> tags with class 'product-link-main product-link'
                product_links = soup.select('a.product-link-main.product-link')

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
                next_page_link = soup.select_one('a.next')  # Adjust selector if pagination class is different
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
