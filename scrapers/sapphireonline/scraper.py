import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SAPPHIRE_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class SapphireScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=0.1):
        super().__init__(
            base_url="https://pk.sapphireonline.pk",
            logger_name=SAPPHIRE_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "sapphireonline"
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
        except Exception as e:
            self.log_debug(f"Exception occured while making request : {e}")
            return product_data

        soup = BeautifulSoup(response.text, 'html.parser')

        try:
            ld_json_scripts = soup.find_all("script", {"type": "application/ld+json"})
            for ld_json in ld_json_scripts:
                try:
                    data = json.loads(ld_json.string.strip())
                    if isinstance(data, list):
                        for d in data:
                            if d.get('@type') == 'Product':
                                product_data = self.parse_ldjson_product(d, product_data)
                    else:
                        if data.get('@type') == 'Product':
                            product_data = self.parse_ldjson_product(data, product_data)
                except Exception:
                    self.log_debug(f"Exception occured while parsing ldjson_product : {e}")
        except Exception as e:
            self.log_debug(f"Exception occured while parsing ldjson_product : {e}")

        try:
            all_scripts = soup.find_all("script")
            for sc in all_scripts:
                text = sc.get_text(separator="\n").strip()
                if "var dataLayerEvent" in text and "ecommerce" in text:
                    start_index = text.find("var dataLayerEvent =")
                    if start_index != -1:
                        text_after = text[start_index:].split("=", 1)[-1].strip()
                        text_after = text_after.split(";", 1)[0]
                        text_after = text_after.strip()
                        if text_after.endswith("}"):
                            try:
                                event_data = json.loads(text_after)
                                detail = event_data.get("ecommerce", {}).get("detail", {})
                                products = detail.get("products", [])
                                if products:
                                    p = products[0]
                                    product_data["sku"] = p.get("id", product_data["sku"])
                                    if not product_data['title'] and product_data['title'] == "":
                                        product_data["title"] = p.get("name", product_data["title"])
                                    product_data["category"] = p.get("category", product_data["category"])
                                    price_str = p.get("price")
                                    try:
                                        if price_str and not product_data['original_price'] and product_data['original_price'] == "":
                                            product_data["original_price"] = float(price_str)
                                    except ValueError:
                                        self.log_debug(f"Exception occured while parsing price : {e}")
                            except Exception:
                                self.log_debug(f"Exception occured while parsing dataLayerEvent : {e}")
        except Exception as e:
            self.log_debug(f"Exception occured while parsing script : {e}")

        try:
            details_block = soup.find("div", {"class": "collapsible-content"}, style=lambda val: val and "display: block" in val)
            if details_block:
                value_div = details_block.find("div", {"id": "collapsible-details-1"})
                if value_div:
                    details_text = value_div.get_text(separator="\n").strip()
                    product_data['attributes']["details_text"] = details_text

                    
                    lines = details_text.splitlines()
                    for line in lines:
                        line = line.strip()
                        if line.lower().startswith("colour:"):
                            product_data['attributes']["color"] = line.split(":", 1)[-1].strip()
                        if line.lower().startswith("fabric:"):
                            product_data["attributes"]["fabric"] = line.split(":", 1)[-1].strip()
        except Exception as e:
            self.log_debug(f"Exception occured while parsing attributes : {e}")

        try:
            breadcrumb_div = soup.find("ol", {"class": "breadcrumb"})
            if breadcrumb_div:
                crumbs = breadcrumb_div.find_all("li")
                product_data['attributes']["breadcrumb"] = [
                    crumb.get_text(strip=True) for crumb in crumbs
                ]
        except Exception as e:
            self.log_debug(f"Exception occured while parsing breadcrumb : {e}")

        try:
            size_items = soup.find_all("div", class_="size-item")
            all_sizes = []

            for si in size_items:
                size_span = si.find("span")
                input_tag = si.find("input")

                if size_span and input_tag:
                    size_text = size_span.get_text(strip=True)
                    input_classes = input_tag.get("class", [])

                    availability = "not-available" not in input_classes

                    if size_text:
                        all_sizes.append({
                            "size": size_text,
                            "availability": availability
                        })

            product_data["variants"] = all_sizes
        except Exception as e:
            self.log_debug(f"Exception occured while parsing variants : {e}")

        return product_data

    def parse_ldjson_product(self, data, product_data):
      
        try:
            product_data["title"] = data.get("name", product_data["title"])
            product_data["description"] = data.get("description", product_data["description"])

            if data.get("sku"):
                product_data["sku"] = data["sku"]

            brand_obj = data.get("brand", {})
            if isinstance(brand_obj, dict):
                product_data["brand"] = brand_obj.get("name", product_data["brand"])
            else:
                product_data["brand"] = product_data["brand"] or brand_obj 

            if data.get("image"):
                if isinstance(data["image"], list):
                    product_data["images"] = data["image"]
                elif isinstance(data["image"], str):
                    product_data["images"] = [data["image"]]

            offers = data.get("offers", {})
            if isinstance(offers, dict):
                product_data["currency"] = offers.get("priceCurrency", product_data["currency"])
                product_data["original_price"] = offers.get("price", product_data["original_price"])
                avail_link = offers.get("availability", "")
                if "InStock" in avail_link:
                    product_data["availability"] = True
                else:
                    product_data["availability"] = False

        except Exception as e:
            self.log_debug(f"Exception occured while parsing product : {e}")


        return product_data

    
    async def scrape_products_links(self, url):
        all_product_links = []
        page_number = 1
        current_url = url
        prv_link = []
        while True:
            try:
                self.log_info(f"Scraping page {page_number}: {current_url}")
                response = await self.async_make_request(
                    current_url
                )
                soup = BeautifulSoup(response.text, "html.parser")
                main_div = soup.find("div", class_="product-grid")

                if main_div:

                    product_links = soup.find_all('a', class_='badge-wrapper-holder')
                    if not product_links:
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    new_link = []
                    for link in product_links:
                        href = link['href']
                        new_link.append(self.base_url + href)
                    
                    if set(new_link) == set(prv_link) or len(new_link) == len(prv_link):
                        self.log_info(f"No products found on page {page_number}. Stopping.")
                        break
                    

                    diff = len(new_link) - len(prv_link)

                    if diff > 0:
                        all_product_links.extend(new_link[-diff:])


                    prv_link = new_link 
                
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