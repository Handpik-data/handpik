import google.generativeai as genai
import requests
from io import BytesIO
from PIL import Image
import mimetypes
from dotenv import load_dotenv
import os
import json
import logging
from utils.LoggerConstants import ENHANCED_DESCRIPTION_LOGGER
import global_constants
import logging.config
import concurrent.futures
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_DIR = os.path.join(SCRIPT_DIR, 'jsondata')
ENHANCED_JSON_DIR = os.path.join(SCRIPT_DIR, 'enhanced_jsondata')
os.makedirs(ENHANCED_JSON_DIR, exist_ok=True)
logger = logging.getLogger(ENHANCED_DESCRIPTION_LOGGER)

sum_prompt_tokens = 0
sum_completion_tokens = 0
sum_total_tokens = 0
def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type(google.api_core.exceptions.InternalServerError)
)
def generate_enhanced_description(product_data):
    model = genai.GenerativeModel(global_constants.GEMINI_MODEL,
                                  system_instruction=global_constants.SYSTEM_PROMPT)
    
    content_parts = []
    processed_images = 0
    image_urls = product_data.get('images', [])
    
    if image_urls:
        for img_url in image_urls:
            try:
                USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                headers = {"User-Agent": USER_AGENT}
                urls_to_try = [img_url]
                if '?' in img_url:
                    urls_to_try.append(img_url.split('?')[0])
                response = None
                for attempt_url in urls_to_try:
                    try:
                        response = requests.get(attempt_url, headers=headers, timeout=30)
                        response.raise_for_status()
                        break 
                    except Exception as e:
                        logger.warning(f"Attempt failed ({attempt_url}): {str(e)}")
                
                if not response:
                    logger.error(f"All download attempts failed for: {img_url}")
                    continue
                
                content_type = response.headers.get('Content-Type', '').split(';')[0]
                if not content_type:
                    content_type = mimetypes.guess_type(img_url)[0] or 'image/jpeg'
                
                if content_type not in ['image/jpeg', 'image/png', 'image/webp']:
                    img = Image.open(BytesIO(response.content))
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    buffer = BytesIO()
                    img.save(buffer, format='JPEG')
                    image_data = buffer.getvalue()
                    content_type = 'image/jpeg'
                else:
                    image_data = response.content
                
                content_parts.append({
                    'mime_type': content_type,
                    'data': image_data
                })
                processed_images += 1
                
            except Exception as e:
                logger.error(f"Image processing error ({img_url}): {str(e)}", exc_info=True)
    
        text_prompt = "Generate enhanced product description based on:\n"
        
        fields_to_include = [
            'store_name', 'title', 'description', 'category', 'original_price', 
            'sale_price', 'brand', 'availability', 'variants', 'attributes'
        ]
        
        for field in fields_to_include:
            value = product_data.get(field)
            if value:
                if isinstance(value, dict):
                    value = ', '.join(f"{k}: {v}" for k, v in value.items())
                
                elif isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    value = '; '.join(
                        ', '.join(f"{k}: {v}" for k, v in item.items()) 
                        for item in value
                    )
                
                elif isinstance(value, list):
                    value = ', '.join(map(str, value))
                text_prompt += f"{field.replace('_', ' ').title()}: {value}\n"
        
        text_prompt += f"\nProcessed {processed_images} product images\n"

        content_parts.append(text_prompt)

    
    try:
        response = model.generate_content(content_parts)
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
        
        if hasattr(response, 'usage_metadata'):
            token_usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count
            }
        global sum_prompt_tokens, sum_completion_tokens, sum_total_tokens
        sum_prompt_tokens = sum_prompt_tokens + token_usage['prompt_tokens']
        sum_completion_tokens = sum_completion_tokens + token_usage['completion_tokens']
        sum_total_tokens = sum_total_tokens + token_usage['total_tokens']
        

        return response.text
    
    except google.api_core.exceptions.InternalServerError as e:
        logger.warning(f"Google server error: {str(e)} - Retrying...")
        raise 
    except Exception as e:
        logger.error(f"Generation failed: {str(e)}", exc_info=True)
        return None
    
def process_single_product(product, index, total_products):
    product_id = product.get('product_url', f"Product#{index+1}")
    logger.info(f"Processing product {index+1}/{total_products}: {product_id}")
    try:
        enhanced_desc = generate_enhanced_description(product)
        product['enhanced_description'] = enhanced_desc
    except Exception as e:
        logger.error(f"Error processing product {product_id}: {str(e)}", exc_info=True)
        product['enhanced_description'] = None
    
    return product

def process_json_files():
    for filename in os.listdir(JSON_DIR):
        if not filename.endswith('.json'):
            continue
        if filename == "cambridgeshop.json" or filename == "saeedghani.json":
            logger.warning(f"Store {filename} already processed")
            continue
            
        input_path = os.path.join(JSON_DIR, filename)
        output_path = os.path.join(ENHANCED_JSON_DIR, filename)
        
        logger.info(f"Processing {filename}...")
        
        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                products = json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {str(e)}", exc_info=True)
            continue
            
        total_products = len(products)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for idx, product in enumerate(products):
                futures.append(
                    executor.submit(
                        process_single_product, 
                        product, 
                        idx, 
                        total_products
                    )
                )
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Unhandled exception in future: {str(e)}", exc_info=True)
        
        logger.info(f"Token usage: prompt tokens: {sum_prompt_tokens} completion tokens: {sum_completion_tokens} total tokens: {sum_total_tokens}")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved enhanced data to {output_path}")


if __name__ == "__main__":
    setup_logging()
    process_json_files()
    logger.info(f"Processing complete! Enhanced JSONs saved in: {ENHANCED_JSON_DIR}")