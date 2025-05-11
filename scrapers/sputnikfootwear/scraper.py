import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SPUTNIK_LOGGER

class SputnikFootWearScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://sputnikfootwear.com",
            logger_name=SPUTNIK_LOGGER
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        if not os.path.exists(filename):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filename, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))
        
    async def scrape_pdp(self, product_link):
        response = requests.get(product_link)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')

        product_data = {
            'title': None,
            'brand': None,
            'product_type': None,
            'price': None,
            'original_price': None,
            'images': [],
            'variants': [],
            'url': product_link
        }
        product_json_script = soup.find('script', id=lambda x: x and x.startswith("ProductJson"))
        if not product_json_script:
            self.log_error("Error: Product JSON script not found.")
            return product_data

        try:
            product_json = json.loads(product_json_script.string.strip())
        except:
            self.log_error("Error: Could not parse product JSON.")
            return product_data

        product_data['title'] = product_json.get('title')
        product_data['brand'] = product_json.get('vendor')
        product_data['product_type'] = product_json.get('type')

        product_data['price'] = None
        product_data['original_price'] = None

        if 'price' in product_json:
            product_data['price'] = product_json['price'] / 100 if product_json['price'] else None

        if 'compare_at_price' in product_json and product_json['compare_at_price']:
            product_data['original_price'] = product_json['compare_at_price'] / 100

    
        all_images = product_json.get('images', [])
        product_data['images'] = [
            img.replace('//', 'https://') for img in all_images
        ]
        variants_list = product_json.get('variants', [])

        for v in variants_list:
            variant_info = {}
            variant_info['size'] = v.get('option1')
            variant_info['color'] = v.get('option2')
            variant_info['available'] = v.get('available', False)
            variant_info['price'] = v['price'] / 100.0 if v.get('price') else None
            variant_info['original_price'] = (v['compare_at_price'] / 100.0 
                                                if v.get('compare_at_price') else None)
            
            product_data['variants'].append(variant_info)

        return product_data
    
    async def get_product_links(self, page_url):
        response = requests.get(page_url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        product_links = []
        for link_tag in soup.select(".grid-view-item__link"):
            href = link_tag.get("href")
            if href and "/products/" in href:
                full_link = self.base_url + href
                product_links.append(full_link)

        
        next_page = None
        infinite_link = soup.select_one("a.infinite")
        if infinite_link and infinite_link.get("href"):
            next_page = self.base_url + infinite_link.get("href")

        return product_links, next_page

    async def scrape_products_links(self, url):
        all_product_links = []

        while url:
            self.log_info(f"Scraping : {url}")
            product_links, next_page = await self.get_product_links(url)
            
            all_product_links.extend(product_links)
            
            if not next_page:
                self.log_info(f"No products found on {url}. Stopping.")
                break
            
            url = next_page
                    
        return all_product_links

    async def scrape_category(self, url):
        all_products = []
        all_products_links = await self.scrape_products_links(url)
        for product_link in all_products_links:
            pdp_data = await self.scrape_pdp(product_link)
            all_products.append(pdp_data)
        
        return all_products
    
    async def scrape_data(self):
        final_data = []
        try:
            category_urls = await self.get_unique_urls_from_file(os.path.join(self.module_dir, "categories.txt"))
            for url in category_urls:
                products = await self.scrape_category(url)
                final_data.extend(products)
                
            if final_data:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M")
                output_file = f"sputnikProducts_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_file)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)
                
                self.log_info(f"Total {len(category_urls)} categories")
                self.log_info(f"Saved {len(final_data)} products into sputnikProducts.json")
                self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")

            else:
                self.log_error("No data scraped")
                        
        except Exception as e:
            self.log_error(f"Error: {e}")    