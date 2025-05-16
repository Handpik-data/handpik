import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SHEEPOFFICIAL_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class SheepOfficialScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://sheepofficial.com",
            logger_name=SHEEPOFFICIAL_LOGGER
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
        session = requests.Session()
        retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[509, 510, 511, 512],
        allowed_methods=frozenset(['GET', 'POST'])
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        response = session.get(
            product_link,
            verify=False, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                            '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            },
            timeout=15
        )
        soup = BeautifulSoup(response.text, 'html.parser')

        product_data = {
            'url': product_link,
            'title': None,
            'description': None,
            'sku': None,
            'category': None,
            'brand': None,
            'compare_price': None,
            'sale_price': None,
            'currency': None,
            'images': [],
            'availability': None,
        }


        ld_json_scripts = soup.find_all('script', type='application/ld+json')
        for tag in ld_json_scripts:
            try:
                data = json.loads(tag.string)
                if isinstance(data, list):
                    for block in data:
                        if isinstance(block, dict) and block.get('@type') == 'Product':
                            product_data = await self.parse_ldjson_product(block, product_data)
                elif isinstance(data, dict) and data.get('@type') == 'Product':
                    product_data = await self.parse_ldjson_product(data, product_data)
            except (json.JSONDecodeError, TypeError):
                continue

        title_el = soup.select_one('.t4s-product__title')
        if title_el and title_el.get_text(strip=True):
            product_data['title'] = title_el.get_text(strip=True)

        desc_el = soup.select_one('.t4s-product__description .t4s-rte')
        if desc_el:
            product_data['description'] = desc_el.get_text('\n', strip=True)

        sku_el = soup.select_one('[data-product__sku-number]')
        if sku_el:
            product_data['sku'] = sku_el.get_text(strip=True)

        del_el = soup.select_one('.t4s-product__price-review del .money')
        if del_el:
            del_text = del_el.get_text(strip=True).replace('Rs.', '').replace(',', '')
            product_data['compare_price'] = del_text if del_text else None

        ins_el = soup.select_one('.t4s-product__price-review ins .money')
        if ins_el:
            ins_text = ins_el.get_text(strip=True).replace('Rs.', '').replace(',', '')
            product_data['sale_price'] = ins_text if ins_text else None

        product_data['images'] = list(dict.fromkeys(product_data['images']))

        return product_data
    

    async def parse_ldjson_product(self, ldjson_obj, product_data):
  
        if ldjson_obj.get('name'):
            product_data['title'] = ldjson_obj['name'].strip()

        if ldjson_obj.get('description'):
            product_data['description'] = ldjson_obj['description'].strip()

        if ldjson_obj.get('sku'):
            product_data['sku'] = ldjson_obj['sku'].strip()

        if ldjson_obj.get('category'):
            product_data['category'] = ldjson_obj['category'].strip()

        brand_obj = ldjson_obj.get('brand', {})
        if isinstance(brand_obj, dict) and brand_obj.get('name'):
            product_data['brand'] = brand_obj['name'].strip()

        if ldjson_obj.get('image'):
            if isinstance(ldjson_obj['image'], list):
                for img_src in ldjson_obj['image']:
                    product_data['images'].append(img_src.strip())
            else:
                product_data['images'].append(ldjson_obj['image'].strip())

        offers_obj = ldjson_obj.get('offers', {})
        if isinstance(offers_obj, dict):
            if offers_obj.get('price'):
                product_data['sale_price'] = offers_obj['price']
            if offers_obj.get('priceCurrency'):
                product_data['currency'] = offers_obj['priceCurrency']
            if offers_obj.get('availability'):
                product_data['availability'] = offers_obj['availability'].split('/')[-1]

        return product_data
    
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

                main_div = soup.find('div', class_='t4s-product-wrapper')

                if main_div:

                    product_links = soup.find_all('div', class_='t4s-product')
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    for link in product_links:
                        product_link = link.find('a', {'class': 't4s-pr-addtocart'})
                        href = product_link['href']
                        all_product_links.append(self.base_url + href)
                else:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
                            
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
                output_file = f"sheepOfficialProducts_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_file)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)
                
                self.log_info(f"Total {len(category_urls)} categories")
                self.log_info(f"Saved {len(final_data)} products into sheepOfficialProducts.json")
                self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")

            else:
                self.log_error("No data scraped")
                        
        except Exception as e:
            self.log_error(f"Error: {e}")    