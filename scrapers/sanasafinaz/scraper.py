import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SANASAFINAZ_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from bs4.element import NavigableString

class SanaSafinazScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://www.sanasafinaz.com",
            logger_name=SANASAFINAZ_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "sanasafinaz"
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
        if price_str.startswith("£"):
            price_str = price_str[1:]
        return price_str
        
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
            soup = BeautifulSoup(response.text, "html.parser")

            product_info_main = soup.find('div', class_="product-info-main")
            if product_info_main:
                try:
                    page_title_wrapper = product_info_main.find('div', class_="page-title-wrapper")
                    if page_title_wrapper:
                        page_title_span = product_info_main.find('span', class_="base")
                        product_data["title"] = page_title_span.get_text(strip=True)
                    
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's title : {e}")

                
                try:
                    page_sku_wrapper = product_info_main.find('strong', class_="type")
                    if page_sku_wrapper:
                        page_sku_div = page_sku_wrapper.find_next('div')
                        product_data["sku"] = page_sku_div.get_text(strip=True)
                    
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's sku : {e}")

                try:
                    page_price_wrapper = product_info_main.find('div', class_="price-box")
                    if page_price_wrapper:
                        page_special_price = page_price_wrapper.find('span', class_="special-price")
                        if page_special_price:
                            page_old_price = page_price_wrapper.find('span', class_="old-price")
                            product_data["sale_price"] = await self.clean_price_string(page_special_price.find('span', class_="price").get_text(strip=True))
                            product_data["original_price"] = await self.clean_price_string(page_old_price.find('span', class_="price").get_text(strip=True))
                        else:
                            price_final_price = page_price_wrapper.find('span', class_="price-final_price")
                            if price_final_price:
                                product_data["original_price"] = await self.clean_price_string(price_final_price.find('span', class_="price").get_text(strip=True))              
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's price : {e}")
                
                try:

                    script_tag = soup.find("script", type="text/x-magento-init", string=re.compile(r"\[data-role=swatch-options\]"))
                    if script_tag:
                        data = json.loads(script_tag.string)

                        swatch_data = data.get("[data-role=swatch-options]", {})
                        renderer_data = swatch_data.get("Magento_Swatches/js/swatch-renderer", {})
                        attributes = renderer_data.get("jsonConfig", {}).get("attributes", {})
                        sizes = []
                        for attr in attributes.values():
                            if attr.get("code", "").lower() == "size":
                                sizes = [opt["label"] for opt in attr.get("options", [])]
                                break
                        variants = [{'size': size} for size in sizes]
                        product_data["variants"] = variants
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's sizes : {e}")
                
                try:
                    images_container = soup.find('div', class_="MagicToolboxContainer")
                    image_urls = []
                    if images_container:
                        for img in images_container.find_all('img'):
                            src = img.get('src')
                            if src:
                                image_urls.append(src)
                    product_data["images"] = image_urls
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's images : {e}")
                
                try:
                    product_details_tag = product_info_main.find('strong', class_='type', string='Product Details:')

                    if product_details_tag:
                        product_container = product_details_tag.find_next('div')
                        for p in product_container.find_all('p'):
                            strong = p.find('strong')
                            if strong and strong.string:
                                attribute_name = strong.string.strip().rstrip(':') 
                                full_text = p.get_text(strip=True)
                                value = full_text.replace(strong.string, '').strip()
                                if attribute_name == "Description":
                                    product_data['description'] = value
                                else:
                                    if ':' in attribute_name:
                                        key, val = attribute_name.split(':', 1)
                                        key = key.strip()
                                        val = val.strip()
                                        if not value:
                                            value = val
                                        else:
                                            value = f"{val} {value}"
                                        attribute_name = key
                                    product_data['attributes'][attribute_name] = value
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's product details : {e}")

            
        except Exception as e:
            self.log_error(f"An error occurred while scraping PDP: {e}")
        
        return product_data
    
    async def scrape_products_links(self, url):
        all_product_links = set()
        page_number = 1
        current_url = url
        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(
                    current_url
                )
                
                soup = BeautifulSoup(response.text, 'html.parser')
                main_div = soup.find_all('ol', class_='product-items')

                if main_div and len(main_div) >= 2:

                    product_links = soup.find_all('div', class_='product-item-info')
                    self.log_info(f"{len(product_links)} products on page {page_number}") 
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    for link in product_links:
                        product_link_a = link.find("a", class_="product")
                        if product_link_a and 'href' in product_link_a.attrs:
                            href = product_link_a['href']
                            all_product_links.add(href)
                else:
                    self.log_info(f"No products found on page {page_number}. Stopping.")
                    break
       
                page_number += 1
                current_url = f"{url}?p={page_number}" if "?" not in url else f"{url}&p={page_number}"
                
            except Exception as e:
                self.log_error(f"Error scraping page {page_number}: {e}")
                break
        
        return list(all_product_links)

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