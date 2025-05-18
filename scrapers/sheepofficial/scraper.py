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
        

    def format_price(self, raw_price: str) -> str:
        cleaned = raw_price.strip()

        cleaned = cleaned.replace("Rs.", "")
        cleaned = cleaned.replace(",", "")
        cleaned = cleaned.strip()

        return cleaned
        
    async def scrape_pdp(self, product_link: str) -> dict:
        product_data = {
            "product_title": None,
            "product_price": None,
            "product_sale_price": None,
            "product_description": None,
            "product_images": None,
            "product_sku": None,
            "product_brand": None,
            "product_category": None,
            "product_tags": None,
            "product_availability": None,
            "product_rating": None,
            "product_reviews_count": None,
            "product_link": product_link,
            "product_currency": None,
        }

        session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[509, 510, 511, 512],
            allowed_methods=frozenset(['GET', 'POST'])
        )
        session.mount('https://', HTTPAdapter(max_retries=retries))

        try:
            resp = session.get(
                product_link,
                verify=False,  
                headers={
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/91.0.4472.124 Safari/537.36'
                    )
                },
                timeout=15
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            self.log_error(f"Error fetching {product_link}: {e}")
            return product_data  

        soup = BeautifulSoup(resp.text, "html.parser")

        try:
            
            title_tag = soup.find("title")
            if title_tag:
                product_data["product_title"] = title_tag.get_text(strip=True)

         
            price_wrap = soup.select_one(".t4s-product-price")
            if price_wrap:
                del_tag = price_wrap.select_one("del .money")
                if del_tag:
                    product_data["product_price"] = self.format_price(del_tag.get_text(strip=True))
                ins_tag = price_wrap.select_one("ins .money")
                if ins_tag:
                    product_data["product_sale_price"] = self.format_price(ins_tag.get_text(strip=True))
                else:
                
                    if not del_tag:
                        money_tag = price_wrap.select_one(".money")
                        if money_tag:
                            product_data["product_price"] = money_tag.get_text(strip=True)
                            product_data["product_sale_price"] = None

            desc_wrap = soup.select_one(".t4s-product__description .t4s-rte")
            if desc_wrap:
                product_data["product_description"] = desc_wrap.get_text(" ", strip=True)

            img_tags = soup.select('.t4s-product__media-item img')
            if img_tags:
                product_data["product_images"] = []
                for tag in img_tags:
             
                    src_master = tag.get("data-master")
                    if src_master and src_master.strip():
                        product_data["product_images"].append("https:" + src_master.strip())
                    else:
                        src_url = tag.get("src") or ""
                        if src_url.strip():
                            product_data["product_images"].append("https:" + src_url.strip())

                product_data["product_images"] = list(dict.fromkeys(product_data["product_images"]))

          
            sku_tag = soup.select_one('[data-product__sku-number]')
            if sku_tag:
                sku_value = sku_tag.get_text(strip=True)
                if sku_value:
                    product_data["product_sku"] = sku_value

           
            ld_json_scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script_tag in ld_json_scripts:
                try:
                    data_json = json.loads(script_tag.string or "")
                   
                    if isinstance(data_json, dict):
                        brand_info = data_json.get("brand") or {}
                        if isinstance(brand_info, dict):
                            brand_name = brand_info.get("name")
                            if brand_name:
                                product_data["product_brand"] = brand_name
                      
                        if data_json.get("category"):
                            product_data["product_category"] = data_json["category"]
                    elif isinstance(data_json, list):
                        for item in data_json:
                            if isinstance(item, dict):
                                if item.get("brand"):
                                    brand_info = item["brand"]
                                    if isinstance(brand_info, dict):
                                        brand_name = brand_info.get("name")
                                        if brand_name:
                                            product_data["product_brand"] = brand_name
                                if item.get("category"):
                                    product_data["product_category"] = item["category"]
                except json.JSONDecodeError:
                    pass

            
            tags_holder = soup.select(".product-tags a") or soup.select(".tags a")
            if tags_holder:
                product_data["product_tags"] = [t.get_text(strip=True) for t in tags_holder]

            for script_tag in ld_json_scripts:
                try:
                    data_json = json.loads(script_tag.string or "")
                    if isinstance(data_json, dict) and data_json.get("@type") == "ProductGroup" and "hasVariant" in data_json:
                      
                        variants = data_json["hasVariant"]
                        for variant in variants:
                            offers = variant.get("offers", {})
                            if isinstance(offers, dict):
                                if "availability" in offers:
                                    if "InStock" in offers["availability"]:
                                        product_data["product_availability"] = "In Stock"
                                        break
                except json.JSONDecodeError:
                    pass
            if not product_data["product_availability"]:
            
                if "Sold out" in soup.get_text():
                    product_data["product_availability"] = "Out of Stock"
                else:
                    product_data["product_availability"] = "In Stock"

       
            rating_tag = soup.select_one(".r--stars-icon, .jdgm-stars")
            if rating_tag and rating_tag.get("data-average-rating"):
                product_data["product_rating"] = rating_tag["data-average-rating"]

            reviews_count_tag = soup.select_one(".reviews-count, .jdgm-rating-summary__count")
            if reviews_count_tag:
                product_data["product_reviews_count"] = reviews_count_tag.get_text(strip=True)

           
            currency_meta = soup.find("meta", {"itemprop": "priceCurrency"})
            if currency_meta and currency_meta.get("content"):
                product_data["product_currency"] = currency_meta["content"].strip()
            else:
                for script_tag in ld_json_scripts:
                    try:
                        data_json = json.loads(script_tag.string or "")
                        if isinstance(data_json, dict):
                            if data_json.get("@type") == "ProductGroup" and data_json.get("hasVariant"):
                                for variant in data_json["hasVariant"]:
                                    offers = variant.get("offers", {})
                                    if offers and offers.get("priceCurrency"):
                                        product_data["product_currency"] = offers["priceCurrency"]
                                        break
                    except json.JSONDecodeError:
                        pass

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