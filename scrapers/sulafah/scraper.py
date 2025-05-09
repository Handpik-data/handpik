import os
import json
import requests
import re
from bs4 import BeautifulSoup
from interfaces.base_scraper import BaseScraper
from datetime import datetime
from utils.LoggerConstants import SULFAH_LOGGER

class SulafahScraper(BaseScraper):
    def __init__(self):
        super().__init__(
            base_url="https://sulafah.com.pk",
            logger_name=SULFAH_LOGGER
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

        title_tag = soup.select_one('.product-info__block-item[data-block-type="title"] .product-title')
        title = title_tag.get_text(strip=True) if title_tag else None

        sale_price_tag = soup.select_one('.price-list--product sale-price .money')
        sale_price = re.sub(r'[^0-9.]', '', sale_price_tag.get_text(strip=True))[1:] if sale_price_tag else None

        compare_price_tag = soup.select_one('.price-list--product compare-at-price:not([hidden]) .money')
        compare_price = re.sub(r'[^0-9.]', '', compare_price_tag.get_text(strip=True))[1:] if compare_price_tag else None


        desc_section = soup.select_one('.product-info__block-item[data-block-type="description"] .prose')
        description = desc_section.get_text("\n", strip=True) if desc_section else None

        images = []
        for media in soup.select('.product-gallery__carousel .product-gallery__media'):
            img_tag = media.find('img')
            if img_tag and img_tag.get('src'):
                photo_url = img_tag['src']
                photo_url = f"https:{photo_url}" if photo_url.startswith('//') else photo_url
                images.append(photo_url)

        variants = []
        for label in soup.select('.variant-picker__option-values label.block-swatch'):
            value_span = label.select_one('span')
            if not value_span:
                continue

            variant_value = value_span.get_text(strip=True)
            is_disabled = ('is-disabled' in label.get('class', []))
            variants.append({
                'value': variant_value,
                'available': not is_disabled
            })
        
        if len(variants) > 0:
            if variants[len(variants)-1]['value'] == '':
                variants = variants[:-1]
        product_data = {
            'title': title,
            'price': sale_price,
            'compare_at_price': compare_price,
            'description': description,
            'images': images,
            'variants': variants,
            'url': product_link
        }
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
                output_file = f"sulafahProducts_{timestamp}.json"
                output_path = os.path.join(self.module_dir, output_file)
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(final_data, f, indent=4, ensure_ascii=False)
                self.log_info(f"Saved {len(final_data)} products into sulafahProducts.json")
            else:
                self.log_error("No data scraped")
                        
        except Exception as e:
            self.log_error(f"Error: {e}")    