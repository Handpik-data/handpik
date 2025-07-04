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

def generate_enhanced_description(image_urls=None, text_description=None, title=None, category=None, colors=None):
    model = genai.GenerativeModel(global_constants.GEMINI_MODEL,
                                  system_instruction=global_constants.SYSTEM_PROMPT)
    
    content_parts = []
    
    max_images = 5
    processed_images = 0
    
    if image_urls:
        for img_url in image_urls[:max_images]:
            try:
                response = requests.get(img_url, timeout=10)
                response.raise_for_status()
                
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
    if title:
        text_prompt += f"Title: {title}\n"
    if text_description:
        text_prompt += f"Existing Description: {text_description}\n"
    if category:
        category_str = ", ".join(category)
        text_prompt += f"Category: {category_str}\n"
    if colors:
        colors_str = ", ".join(colors)
        text_prompt += f"Available Colors: {colors_str}\n"
    
    text_prompt += f"Processed {processed_images} product images\n\n"
    
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
        
        logger.info(f"Token usage: {token_usage}")

        return response.text
            
    except Exception as e:
        logger.error(f"Generation failed: {str(e)}", exc_info=True)
        return None
    
def process_single_product(product, index, total_products):
    product_id = product.get('product_url', f"Product#{index+1}")
    logger.info(f"Processing product {index+1}/{total_products}: {product_id}")
    
    images = product.get('images', [])
    text_desc = product.get('description')
    title = product.get('title')
    category = product.get('category') or []
    variants = product.get('variants', [])
    colors = list(set(variant.get("Color") for variant in variants if variant.get("Color")))
    
    try:
        enhanced_desc = generate_enhanced_description(
            image_urls=images,
            text_description=text_desc,
            title=title,
            category=category,
            colors=colors 
        )
        product['enhanced_description'] = enhanced_desc
    except Exception as e:
        logger.error(f"Error processing product {product_id}: {str(e)}", exc_info=True)
        product['enhanced_description'] = None
    
    return product

def process_json_files():
    for filename in os.listdir(JSON_DIR):
        if not filename.endswith('.json'):
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