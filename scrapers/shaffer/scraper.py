import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SHAFFER_LOGGER
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

class ShafferScraper(BaseScraper):
    def __init__(self, proxies=None, request_delay=3):
        super().__init__(
            base_url="https://shaffer.store",
            logger_name=SHAFFER_LOGGER,
            proxies=proxies,
            request_delay=request_delay
        )
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.store_name = "shaffer"
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
            soup = BeautifulSoup(response.text, "html.parser")

            try:
                h1_tag = soup.find("h1", class_="main-product__title")
                product_data["title"] = h1_tag.get_text(strip=True) if h1_tag else None
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's titles : {e}")

            try:
                canonical = soup.find("link", rel="canonical")
                if canonical and canonical.get("href"):
                    url_parts = canonical["href"].rstrip("/").split("/")
                    handle = url_parts[-1].split("?")[0]
                    product_data["category"] = handle
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's category : {e}")

            try:
                brand_tag = soup.find("p", class_="underlined-link--no-offset")
                if brand_tag:
                    product_data["brand"] = brand_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's brand : {e}")

            try:
                og_price = soup.find("meta", attrs={"property": "og:price:amount"})
                og_currency = soup.find("meta", attrs={"property": "og:price:currency"})
                if og_price and og_price.get("content"):
                    cleaned_price = og_price["content"].replace(",", "")
                    product_data["original_price"] = float(cleaned_price)
                if og_currency and og_currency.get("content"):
                    product_data["currency"] = og_currency["content"]
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's currency and original price : {e}")

            try:
                desc_div = soup.find("div", class_="accordion__content p2 p2--fixed rte")
                if desc_div:
                    product_data["description"] = desc_div.get_text(separator="\n", strip=True)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's description : {e}")

            try:
                inv_tag = soup.find("div", class_="main-product__inventory-notice")
                if inv_tag:
                    product_data['attributes']["inventory_text"] = inv_tag.get_text(strip=True)
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's attributes : {e}")

            try:
                
                images_found = soup.select("div.main-product__media-item img")
                images = []
                for im in images_found:
                    src = im.get("src") or ""
                    if src and src not in images:
                        images.append("https:" + src)
                product_data["images"] = images
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's images : {e}")

      
            try:
                ld_json_tag = soup.find("script", type="application/ld+json", text=lambda t: '"availability"' in t if t else False)
                if ld_json_tag:
                    text_json = ld_json_tag.string.strip()
                    if '"availability" : "http://schema.org/InStock"' in text_json:
                        product_data["availability"] = True
                    else:
                        product_data["availability"] = False
            except Exception as e:
                self.log_debug(f"Exception occured while scraping product's availability : {e}")

        

        except Exception as e:
            self.log_error(f"An error occurred while scraping: {e}")
        
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
                main_div = soup.find('ul', class_='product-grid')

                if main_div:

                    product_links = soup.find_all('a', class_='product-card__link')
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