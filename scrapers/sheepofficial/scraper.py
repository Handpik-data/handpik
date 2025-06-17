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
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://sheepofficial.com",
            logger_name=SHEEPOFFICIAL_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "sheepofficial"
        self.all_product_links_ = []

    async def get_unique_urls_from_file(self, filename):
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("Filename must be a non-empty string.")
        
        if not os.path.exists(filename):
            raise FileNotFoundError(f"The file '{filename}' does not exist.")
        
        with open(filename, 'r') as file:
            return list(set(line.strip() for line in file if line.strip()))
        

    def format_price(self, raw_price: str) -> str:
        cleaned = raw_price.strip()

        cleaned = cleaned.replace("Rs.", "")
        cleaned = cleaned.replace(",", "")
        cleaned = cleaned.strip()

        return cleaned
        
    async def scrape_pdp(self, product_link: str) -> dict:
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
        except requests.RequestException as e:
            self.log_debug(f"Error fetching {product_link}: {e}")
            return product_data  

        soup = BeautifulSoup(response, "html.parser")

        try:
            
            title_tag = soup.find("title")
            if title_tag:
                product_data["title"] = title_tag.get_text(strip=True)
            
            variants_script = soup.find('script', class_='pr_variants_json')
            if variants_script:
                variants_data = json.loads(variants_script.string)
            else:
                variants_data = []

            
            options_script = soup.find('script', class_='pr_options_json')
            if options_script:
                options_data = json.loads(options_script.string)
            else:
                options_data = []

            option_map = [{opt["position"]: opt["name"].lower()} for opt in options_data]



            variants = []
            for variant in variants_data:
                variant_data = {}
                for i in option_map:
                    for key, value in i.items():
                        variant_data[value] = variant.get('option' + str(key), '')

                variant_data['availability'] = variant.get('available', False)
                
                variants.append(variant_data)

            product_data['variants'] = variants

         
            price_wrap = soup.select_one(".t4s-product-price")
            if price_wrap:
                del_tag = price_wrap.select_one("del .money")
                if del_tag:
                    product_data["original_price"] = self.format_price(del_tag.get_text(strip=True))
                ins_tag = price_wrap.select_one("ins .money")
                if ins_tag:
                    product_data["sale_price"] = self.format_price(ins_tag.get_text(strip=True))
                else:
                
                    if not del_tag:
                        money_tag = price_wrap.select_one(".money")
                        if money_tag:
                            product_data["original_price"] = money_tag.get_text(strip=True)

            desc_wrap = soup.select_one(".t4s-product__description .t4s-rte")
            if desc_wrap:
                product_data["description"] = desc_wrap.get_text(" ", strip=True)

            img_tags = soup.select('.t4s-product__media-item img')
            if img_tags:
                product_data["images"] = []
                for tag in img_tags:
             
                    src_master = tag.get("data-master")
                    if src_master and src_master.strip():
                        product_data["images"].append("https:" + src_master.strip())
                    else:
                        src_url = tag.get("src") or ""
                        if src_url.strip():
                            product_data["images"].append("https:" + src_url.strip())

                product_data["images"] = list(dict.fromkeys(product_data["images"]))

          
            sku_tag = soup.select_one('[data-product__sku-number]')
            if sku_tag:
                sku_value = sku_tag.get_text(strip=True)
                if sku_value:
                    product_data["sku"] = sku_value

           
            ld_json_scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script_tag in ld_json_scripts:
                try:
                    data_json = json.loads(script_tag.string or "")
                   
                    if isinstance(data_json, dict):
                        brand_info = data_json.get("brand") or {}
                        if isinstance(brand_info, dict):
                            brand_name = brand_info.get("name")
                            if brand_name:
                                product_data["brand"] = brand_name
                      
                        if data_json.get("category"):
                            product_data["category"] = data_json["category"]
                    elif isinstance(data_json, list):
                        for item in data_json:
                            if isinstance(item, dict):
                                if item.get("brand"):
                                    brand_info = item["brand"]
                                    if isinstance(brand_info, dict):
                                        brand_name = brand_info.get("name")
                                        if brand_name and not product_data['brand'] and  product_data['brand'] == "":
                                            product_data["brand"] = brand_name
                                if item.get("category") and not product_data['category'] and  product_data['category'] == "":
                                    product_data["category"] = item["category"]
                except Exception as e:
                    self.log_debug(f"Exception occured while scraping product's ld script : {e}")

            
            tags_holder = soup.select(".product-tags a") or soup.select(".tags a")
            if tags_holder:
                product_data['attributes']["product_tags"] = [t.get_text(strip=True) for t in tags_holder]

       
            rating_tag = soup.select_one(".r--stars-icon, .jdgm-stars")
            if rating_tag and rating_tag.get("data-average-rating"):
                product_data['attributes']["product_rating"] = rating_tag["data-average-rating"]

            reviews_count_tag = soup.select_one(".reviews-count, .jdgm-rating-summary__count")
            if reviews_count_tag:
                product_data['attributes']["product_reviews_count"] = reviews_count_tag.get_text(strip=True)

           
            currency_meta = soup.find("meta", {"itemprop": "priceCurrency"})
            if currency_meta and currency_meta.get("content"):
                product_data["currency"] = currency_meta["content"].strip()
            else:
                for script_tag in ld_json_scripts:
                    try:
                        data_json = json.loads(script_tag.string or "")
                        if isinstance(data_json, dict):
                            if data_json.get("@type") == "ProductGroup" and data_json.get("hasVariant"):
                                for variant in data_json["hasVariant"]:
                                    offers = variant.get("offers", {})
                                    if offers and offers.get("priceCurrency") and not product_data['currency'] and product_data['currency'] == "":
                                        product_data["currency"] = offers["priceCurrency"]
                                        break
                    except Exception as e:
                        self.log_debug(f"Exception occured while scraping product's currency : {e}")

        except Exception as e:
            self.log_error(f"Error scraping {product_link}: {e}")

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