import asyncio
import os
import json
import logging
import google.generativeai as genai
import concurrent.futures
from database import create_pool, setup_partitioned_table, get_existing_description, insert_products
from utils.LoggerConstants import ENHANCED_DESCRIPTION_LOGGER
import global_constants
from dotenv import load_dotenv
import requests
from io import BytesIO
from PIL import Image
import mimetypes
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import google
from datetime import datetime
import threading
import logging.config 

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

setup_logging()

logger = logging.getLogger(ENHANCED_DESCRIPTION_LOGGER)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_DIR = os.path.join(SCRIPT_DIR, global_constants.JSONDATA)
ENHANCED_JSON_DIR = os.path.join(SCRIPT_DIR, global_constants.ENHANCEDDATA)
os.makedirs(ENHANCED_JSON_DIR, exist_ok=True)

sum_prompt_tokens = 0
sum_completion_tokens = 0
sum_total_tokens = 0
token_lock = threading.Lock()

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
    
    if content_parts: 
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
        if not content_parts:
            logger.warning("No content parts available for generation")
            return product_data.get("product_url"), None
            
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
        
        with token_lock:
            global sum_prompt_tokens, sum_completion_tokens, sum_total_tokens
            sum_prompt_tokens += token_usage['prompt_tokens']
            sum_completion_tokens += token_usage['completion_tokens']
            sum_total_tokens += token_usage['total_tokens']
        
        return product_data.get("product_url"), response.text

    
    except google.api_core.exceptions.InternalServerError as e:
        logger.warning(f"Google server error: {str(e)} - Retrying...")
        raise 
    except Exception as e:
        logger.error(f"Generation failed: {str(e)}", exc_info=True)
        return product_data.get("product_url"), None


async def process_file(filename, pool, executor):
    input_path = os.path.join(JSON_DIR, filename)
    output_path = os.path.join(ENHANCED_JSON_DIR, filename)
    
    logger.info(f"Processing {filename}...")
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            products = json.load(f)
    except Exception as e:
        logger.error(f"Error loading {filename}: {str(e)}", exc_info=True)
        return 0
    
    existing_descriptions = {}
    for product in products:
        product_url = product.get('product_url')
        if product_url:
            existing_desc = await get_existing_description(
                pool, 
                global_constants.ENHANCED_DESCRIPRION_TABLE, 
                product_url
            )
            if existing_desc:
                existing_descriptions[product_url] = existing_desc
    
    futures = {}
    product_map = {product.get('product_url'): product for product in products}

    for product in products:
        product_url = product.get('product_url')
        
        if product_url in existing_descriptions:
            product['enhanced_description'] = existing_descriptions[product_url]
            continue
            
        future = executor.submit(generate_enhanced_description, product)
        futures[future] = product_url
    
    generated_count = 0

    for future in concurrent.futures.as_completed(futures):
        product_url = futures[future]
        try:
            returned_url, enhanced_desc = future.result()
            if returned_url != product_url:
                logger.warning(f"Mismatched URLs: expected {product_url}, got {returned_url}")
            if product_url in product_map:
                product_map[product_url]['enhanced_description'] = enhanced_desc
                generated_count += 1
            else:
                logger.warning(f"Product URL not found in product_map: {product_url}")
        except Exception as e:
            logger.error(f"Error generating description for {product_url}: {str(e)}")
            if product_url in product_map:
                product_map[product_url]['enhanced_description'] = None

    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(products, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Enhanced {generated_count} products in {filename}")
    logger.info(f"Saved enhanced data to {output_path}")
    return len(products)

async def run_enhancement():
    pool = await create_pool()
    await setup_partitioned_table(
        pool, 
        global_constants.ENHANCED_DESCRIPRION_TABLE, 
        "enhanced_description TEXT"
    )
    
    total_processed = 0
    start_time = datetime.now()
    
    files = [f for f in os.listdir(JSON_DIR) if f.endswith('.json')]
    if not files:
        logger.info("No JSON files found to process")
        return
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        tasks = [process_file(f, pool, executor) for f in files]
        results = await asyncio.gather(*tasks)
        total_processed = sum(results)
    
    enhanced_files = [f for f in os.listdir(ENHANCED_JSON_DIR) if f.endswith('.json')]
    for filename in enhanced_files:
        filepath = os.path.join(ENHANCED_JSON_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            products = json.load(f)
        await insert_products(pool, global_constants.ENHANCED_DESCRIPRION_TABLE, products)
    
    logger.info(f"Token usage: prompt tokens: {sum_prompt_tokens} completion tokens: {sum_completion_tokens} total tokens: {sum_total_tokens}")
    logger.info(f"Processing completed in {datetime.now() - start_time}")
    logger.info(f"Total products enhanced: {total_processed}")
    
    await pool.close()

if __name__ == "__main__":
    asyncio.run(run_enhancement())