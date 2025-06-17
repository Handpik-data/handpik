import os
import re
import json
import requests
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import WOVWORLD_LOGGER

class WovWorldScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=3):
        super().__init__(
            base_url="https://wovworld.com",
            logger_name=WOVWORLD_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "wovworld"
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
            response = await self.async_make_request(
                product_link
            )

            soup = BeautifulSoup(response.text, 'html.parser')

            product_container = soup.find('div', {'class': 'page-content page-content--product'})
            if not product_container:
                return product_data

            product_title_element = product_container.find('h1', {'class': 'product-single__title'})
            if product_title_element:
                product_data['title'] = product_title_element.text.strip()

            
            description_div = product_container.find('div', class_='product-single__description rte')

            if description_div:
                description_text = description_div.get_text(strip=True)
                product_data['description'] = description_text

            price_span_container = product_container.find('span', {'class': 'product__price'})
            if price_span_container:
                price_span = price_span_container.find('span', {'class': 'money'})
                if price_span:
                    raw_price_text = price_span.get_text(strip=True)
                    numeric_text = re.sub(r'[^0-9.]', '', raw_price_text)
                    product_data['original_price'] = numeric_text[1:] if numeric_text else None


            size_wrapper = product_container.find('div', class_='variant-wrapper variant-wrapper--button js')
            if size_wrapper:
                size_label = size_wrapper.find('label', class_='variant__label', string=lambda x: x and 'Size' in x)
                if size_label:
                    fieldset = size_wrapper.find('fieldset', {'name': 'Size'})
                    if fieldset:
                        variant_divs = fieldset.find_all('div', class_='variant-input')
                        for variant_div in variant_divs:
                            size_input = variant_div.find('input', {'type': 'radio'})
                            size_label_tag = variant_div.find('label', class_='variant__button-label')
                            
                            if size_input and size_label_tag:
                                size_name = size_input.get('value', '').strip()
                            
                                classes_input = size_input.get('class', [])
                                classes_label = size_label_tag.get('class', [])

                                if 'disabled' in classes_input or 'disabled' in classes_label:
                                    availability = False
                                else:
                                    availability = True
                                
                                product_data['variants'].append({
                                    'size': size_name,
                                    'availability': availability
                                })
            
            images_container = soup.find('div', attrs={'data-product-images': True})
            if images_container:
                img_tags = images_container.find_all('img', class_='photoswipe__image')
                for img_tag in img_tags:
                    photo_url = img_tag.get('data-photoswipe-src')
                    if photo_url:
                        photo_url = f"https:{photo_url}" if photo_url.startswith('//') else photo_url
                        product_data['images'].append(photo_url)
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
                response = await self.async_make_request(
                    current_url
                )
                
                soup = BeautifulSoup(response.text, 'html.parser')                
                product_divs = soup.find_all('div', class_='grid-product__content') 
                
                if not product_divs: 
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
                  
                for product in product_divs:
                    link_tag = product.find('a', class_='grid-product__link')
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
                saved_path = await self.save_data(final_data)
                if saved_path:
                    self.log_info(f"Total {len(category_urls)} categories")
                    self.log_info(f"Saved {len(final_data)} products to {saved_path}")
                    self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")
            else:
                self.log_error("No data scraped")
        except Exception as e:
            self.log_error(f"Scraping failed: {str(e)}")