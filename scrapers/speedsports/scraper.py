import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SPEEDSPORTS_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class SpeedSportsScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://speedsports.pk",
            logger_name=SPEEDSPORTS_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "speedsports"
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
            response = self.make_request(
                product_link,
                verify=False,
                headers=self.headers
            )
            soup = BeautifulSoup(response.text, 'html.parser')
        

            title_el = soup.select_one('h1.t4s-product__title')
            product_data['title'] = title_el.get_text(strip=True) if title_el else None

            price_container = soup.select_one('div.t4s-product-price')
            if price_container:
                del_el = price_container.find('del')
                ins_el = price_container.find('ins')
                badge_el = price_container.find('span', class_='t4s-badge-price')

                def clean_price(text):
                    return text.replace('Rs.', '').replace(',', '').strip()

                if del_el and ins_el:
                    product_data['original_price'] = clean_price(del_el.get_text())
                    product_data['sale_price'] = clean_price(ins_el.get_text())
                else:
                    product_data['original_price'] = clean_price(price_container.get_text())


            sku_el = soup.select_one('[data-product__sku-number]')
            product_data['sku'] = sku_el.get_text(strip=True) if sku_el else None

            product_ld_json = soup.find('script', type='application/ld+json', text=re.compile('"@type": "Product"'))
            brand = None
            description = None

            if product_ld_json:
                try:
                    json_str = product_ld_json.string.strip()
                    
                    json_str = re.sub(r'"sku":\s*"(.*?)"",', lambda m: f'"sku": "{m.group(1)}",', json_str)
                    
                    json_str = (json_str
                                .replace('\\u0026quot;', '"')
                                .replace('\\u0026#39;', "'")
                                .replace('&quot;', '"')
                                .replace('&#39;', "'"))
                    
                    ld_data = json.JSONDecoder().decode(json_str)
                    
                    brand = ld_data.get('brand', {}).get('name')
                    description = ld_data.get('description', '')
                    
                    description = description.replace('\n', ' ').strip()
                    
                except Exception as e:
                    self.log_debug(f"Error parsing variants JSON: {e}")
            product_data['brand'] = brand
            product_data['description'] = description
                

            images = []
            main_slides = soup.select('[data-product-single-media-group] [data-main-slide]')
            for slide in main_slides:
                img_el = slide.select_one('img[data-master]')
                if img_el:
                    master_url = img_el.get('data-master')
                    if master_url:
                        images.append("https:" + master_url)
            product_data['images'] = images

        
            variants_data = []
            variants_json_el = soup.find('script', class_='pr_variants_json', type='application/json')
            if variants_json_el and variants_json_el.string:
                try:
                    variants_list = json.loads(variants_json_el.string)
                    
                    options_json_el = soup.find('script', class_='pr_options_json', type='application/json')
                    option_names = []
                    if options_json_el and options_json_el.string:
                        options_data = json.loads(options_json_el.string)
                        sorted_options = sorted(options_data, key=lambda x: x['position'])
                        option_names = [opt['name'] for opt in sorted_options]
                    

                    for var_obj in variants_list:
                        variant_options = {}
                        options = var_obj.get('options', [])
                        for idx, value in enumerate(options):
                            if idx < len(option_names):
                                key = option_names[idx]
                                variant_options[key] = value
                        
                        v_data = {
                            'title': var_obj.get('title'),
                            'price': var_obj.get('price') / 100, 
                            'sku': var_obj.get('sku'),
                            'availability': var_obj.get('available'),
                            **variant_options
                        }
                        variants_data.append(v_data)
                except Exception as e:
                    self.log_debug(f"Error parsing variants JSON: {e}")

            product_data['variants'] = variants_data

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
                response = self.make_request(
                    current_url,
                    verify=False,
                    headers=self.headers
                )
                
                soup = BeautifulSoup(response.text, 'html.parser')   

                main_div = soup.find('div', class_='t4s-main-collection-page')

                if main_div:
                    collection_url = main_div.get('data-collection-url')

                    product_links = main_div.find_all('a', class_='t4s-full-width-link')
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    
                    for link in product_links:
                        href = link.get('href')
                        all_product_links.append(self.base_url + collection_url + href)
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
            if pdp_data is not None:
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
                output_file = f"{self.store_name}_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_file)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)
                
                self.log_info(f"Total {len(category_urls)} categories")
                self.log_info(f"Saved {len(final_data)} products into {self.store_name}_{timestamp}.json")
                self.log_info(f"Product Sample Data: {json.dumps(final_data[0], separators=(',', ':'))}")

            else:
                self.log_error("No data scraped")
                        
        except Exception as e:
            self.log_error(f"Error: {e}")    