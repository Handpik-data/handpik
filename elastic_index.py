from elasticsearch import Elasticsearch
import json
import os
import concurrent.futures
import logging
from utils.LoggerConstants import ELASTIC
import logging.config
from dotenv import load_dotenv

load_dotenv()

elastic_url = os.getenv("ELASTIC_URL")
elastic_user = os.getenv("ELASTIC_USER")
elastic_password = os.getenv("ELASTIC_PASSWORD")
elastic_index = os.getenv("ELASTIC_INDEX")

def setup_logging():
    with open("utils/logging_config.json") as f:
        config = json.load(f)
    logging.config.dictConfig(config)

setup_logging()
logger = logging.getLogger(ELASTIC)

es = Elasticsearch(
    elastic_url,
    basic_auth=(elastic_user, elastic_password),  
    verify_certs=False  
)

if not es.indices.exists(index=elastic_index):
    es.indices.create(index=elastic_index)
    logger.info(f"Created new index: {elastic_index}")
else:
    logger.info(f"Using existing index: {elastic_index}")

ENHANCED_JSON_DIR = "enhanced_jsondata"

def index_products_from_file(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            products = json.load(f)
            
        file_name = os.path.basename(file_path)
        logger.info(f"Processing file: {file_name} with {len(products)} products")
        
        success_count = 0
        for i, product in enumerate(products):
            try:
                doc = {k: v for k, v in product.items() if v is not None}
                
                doc_id = f"{product['product_url']}".replace("/", "_")
                response = es.index(index=elastic_index, id=doc_id, document=doc)
                
                if response['result'] in ['created', 'updated']:
                    success_count += 1
                else:
                    logger.warning(f"Failed to index product {i} in {file_name}: {response}")
                    
            except Exception as e:
                logger.error(f"Error indexing product {i} in {file_name}: {str(e)}", exc_info=True)
        
        logger.info(f"Successfully indexed {success_count}/{len(products)} products from {file_name}")
        return success_count
        
    except Exception as e:
        logger.error(f"Error processing file {file_path}: {str(e)}", exc_info=True)
        return 0

def main():
    json_files = []
    for filename in os.listdir(ENHANCED_JSON_DIR):
        if filename.endswith('.json'):
            json_files.append(os.path.join(ENHANCED_JSON_DIR, filename))
    
    if not json_files:
        logger.warning("No JSON files found in enhanced_jsondata directory")
        return
    
    logger.info(f"Found {len(json_files)} JSON files to process")
    
    total_products_indexed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_file = {executor.submit(index_products_from_file, file): file for file in json_files}
        
        for future in concurrent.futures.as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                count = future.result()
                total_products_indexed += count
                logger.info(f"Completed indexing for {os.path.basename(file_path)}")
            except Exception as e:
                logger.error(f"Exception occurred while processing {file_path}: {str(e)}", exc_info=True)
    
    logger.info(f"Indexing complete! Total products indexed: {total_products_indexed}")

if __name__ == "__main__":
    main()