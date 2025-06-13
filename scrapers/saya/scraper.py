import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SAYA_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4.element import NavigableString

class SayaScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://saya.pk",
            logger_name=SAYA_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "saya"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        if not os.path.exists(filename):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filename, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))
        
    async def clean_price_string(self, price_str):
        if not price_str:
            return None
        cleaned = re.sub(r'(Rs\.?|,|\s)', '', price_str)
        return cleaned
        
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
            soup = BeautifulSoup(response.text, "html.parser")
            
            try:
                options_tag = soup.find('script', class_='pr_options_json')
                options_json_data = options_tag.string.strip()
                options_data = json.loads(options_json_data)

                variants_tag = soup.find('script', class_='pr_variants_json')
                variants_json_data = variants_tag.string.strip()
                variants_data = json.loads(variants_json_data)
                
                variants_availability = []
                for i in variants_data:
                    variants = {}
                    for j in options_data:
                        option_name = j['name']
                        option_position = j['position']
                        option_values = j['values']

                        variant_option = i['option'+str(option_position)]
                        if variant_option in option_values:
                            variants[option_name] = variant_option
                    variants['availability'] = i['available']
                    variants_availability.append(variants)
                product_data['variants'] = variants_availability
            
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's available variants : {e}")

            try: 
                h1_title = soup.find("h1", class_="t4s-product__title")
                if h1_title:
                    product_data["title"] = h1_title.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's title : {e}")

            
            try:
                price_review = soup.find("div", class_="t4s-product__price-review")
                if price_review:
                    del_tag = price_review.find("del")
                    if del_tag:
                        compare_span = del_tag.find("span", class_="money")
                        if compare_span:
                            product_data["original_price"] = await self.clean_price_string(compare_span.get_text(strip=True))

                    ins_tag = price_review.find("ins")
                    if ins_tag:
                        price_span = ins_tag.find("span", class_="money")
                        if price_span:
                            product_data["sale_price"] = await self.clean_price_string(price_span.get_text(strip=True))
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's price : {e}")
            
            try:
                product_meta = soup.find("div", class_="t4s-product_meta")
                if product_meta:
                    sku_wrapper = product_meta.find("div", class_="t4s-sku-wrapper")
                    if sku_wrapper:
                        span = sku_wrapper.find("span", class_="t4s-productMeta__value")
                        if span:
                            product_data["sku"] = span.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's sku : {e}")

            try:    
                script_tags = soup.find_all("script")
                for st in script_tags:
                    content = st.string or ""
                    if "var product =" in content:
                        match = re.search(r'"vendor"\s*:\s*"([^"]+)"', content)
                        if match:
                            product_data["category"] = match.group(1)
                        break
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's category : {e}")
            
            try:
                description_span = soup.find('span', class_='pro_desc')
                if description_span:
                    following_description_div = description_span.find_next('div')
                    if following_description_div:
                        inner_divs = following_description_div.find_all('div', recursive=False)
                        if inner_divs:
                            if len(inner_divs) >=1 :
                                strong_tag = inner_divs[0].find('strong', string='Design:')

                                if strong_tag:
                                    span_tag = strong_tag.find_next('span')
                                    if span_tag:
                                        text_before_br = ''
                                        for content in span_tag.contents:
                                            if isinstance(content, NavigableString):
                                                text_before_br += content.strip()
                                            else:
                                                break
                                        product_data['attributes']['design'] = text_before_br
                            if len(inner_divs) >=2 :
                                strong_tag = inner_divs[1].find('strong', string='Product Detail')

                                if strong_tag:
                                    div_tag = strong_tag.find_next('div')
                                    if div_tag:
                                        product_data['description'] = ''.join(div_tag.stripped_strings)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's description : {e}")
            
            try:
                image_container = soup.find('div', class_='t4s-product__media-wrapper')
                image_elements = image_container.find_all('img', {'data-master': True})

                image_urls = []
                for img in image_elements:
                    data_master = img.get('data-master')
                    if data_master:
                        full_url = f'https:{data_master}' if data_master.startswith('//') else data_master
                        image_urls.append(full_url)

                seen = set()
                unique_image_urls = [url for url in image_urls if not (url in seen or seen.add(url))]
                product_data['images'] = unique_image_urls
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's images : {e}")
        except Exception as e:
            self.log_error(f"An error occurred while scraping PDP: {e}")
        
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

                main_div = soup.find('div', class_='t4s-products')

                if main_div:

                    product_links = soup.find_all('a', class_='t4s-full-width-link')
                    self.log_info(f"{len(product_links)} products on page {page_number}") 
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    for link in product_links:
                        href = link['href']
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