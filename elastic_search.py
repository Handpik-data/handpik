from elasticsearch import Elasticsearch
from dotenv import load_dotenv
import os
load_dotenv()

elastic_url = os.getenv("ELASTIC_URL")
elastic_user = os.getenv("ELASTIC_USER")
elastic_password = os.getenv("ELASTIC_PASSWORD")
elastic_index = os.getenv("ELASTIC_INDEX")
es = Elasticsearch(
    elastic_url,
    basic_auth=(elastic_user, elastic_password),  
    verify_certs=False  
)

def search_products(query):
    body = {
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["brand^2", "category^1", "enhanced_description"],
                "fuzziness": "AUTO"
            }
        },
        "highlight": {
            "fields": {
                "enhanced_description": {}
            }
        }
    }
    return es.search(index=elastic_index, body=body)

if __name__ == "__main__":
    query = input("Enter search query: ")
    results = search_products(query)
    
    print(f"\nFound {results['hits']['total']['value']} results:")
    for hit in results['hits']['hits']:
        product = hit['_source']
        
        if 'highlight' in hit:
            print("Description match:")
            for frag in hit['highlight']['enhanced_description']:
                print(f" - {frag}")
        
        print(f"URL: {product['product_url']}")