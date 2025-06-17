import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SULFAH_LOGGER

class SulafahScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://sulafah.com.pk",
            logger_name=SULFAH_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "sulafah"
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

            title_tag = soup.select_one('.product-info__block-item[data-block-type="title"] .product-title')
            title = title_tag.get_text(strip=True) if title_tag else None
            product_data['title'] = title

            sale_price_tag = soup.select_one('.price-list--product sale-price .money')
            sale_price = re.sub(r'[^0-9.]', '', sale_price_tag.get_text(strip=True))[1:] if sale_price_tag else None
            product_data['sale_price'] = sale_price

            compare_price_tag = soup.select_one('.price-list--product compare-at-price:not([hidden]) .money')
            compare_price = re.sub(r'[^0-9.]', '', compare_price_tag.get_text(strip=True))[1:] if compare_price_tag else None
            product_data['original_price'] = compare_price


            desc_section = soup.select_one('.product-info__block-item[data-block-type="description"] .prose')
            description = desc_section.get_text("\n", strip=True) if desc_section else None
            product_data['description'] = description

            images = []
            for media in soup.select('.product-gallery__carousel .product-gallery__media'):
                img_tag = media.find('img')
                if img_tag and img_tag.get('src'):
                    photo_url = img_tag['src']
                    photo_url = f"https:{photo_url}" if photo_url.startswith('//') else photo_url
                    images.append(photo_url)
            product_data['images'] = images

            scripts = soup.find_all('script', type='application/ld+json')

            sizes = []

            for script in scripts:
                try:
                    data = json.loads(script.string)

                    if isinstance(data, dict) and data.get('@type') == 'Product' and 'offers' in data:
                        for offer in data['offers']:
                            size_str = offer.get('name')
                            availability_url = offer.get('availability')
                            
                            if size_str and size_str.isdigit():
                                size = int(size_str)
                                availability = 'InStock' in availability_url
                                sizes.append({'size': size, 'availability': availability})
                    product_data['variants'] = sizes
                except (json.JSONDecodeError, TypeError):
                    continue
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
                product_divs = soup.find_all("product-card", class_="product-card")   
                
                if not product_divs: 
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
                  
                for product in product_divs:
                    link_tag = product.find("a", class_="product-card__media")
                    if link_tag and link_tag.has_attr("href"):
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