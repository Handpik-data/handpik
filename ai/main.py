import google.generativeai as genai
import requests
from io import BytesIO
from PIL import Image
import mimetypes
from dotenv import load_dotenv
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import global_constants



load_dotenv()

genai.configure(api_key=os.getenv("AIzaSyB7ez22ZxESPwa3rPlDuFdAlrSwMB_SuyA"))

def generate_enhanced_description(image_url=None, text_description=None):
    
    model = genai.GenerativeModel(global_constants.GEMINI_MODEL,
                                  system_instruction=global_constants.SYSTEM_PROMPT)
    
    content_parts = []
    
    if image_url:
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            content_type = response.headers.get('Content-Type', '').split(';')[0]
            if not content_type:
                content_type = mimetypes.guess_type(image_url)[0] or 'image/jpeg'
            
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
            
        except Exception as e:
            print(f"Image processing error: {str(e)}")
    
    text_prompt = "Generate enhanced product description based on:"
    if text_description:
        text_prompt += f"\nExisting description: '{text_description}'"
    else:
        text_prompt += "\nNo text description provided - use only visual analysis"
    
    content_parts.append(text_prompt)
    
    try:
        response = model.generate_content(content_parts)
        return response.text
    except Exception as e:
        return f"Generation failed: {str(e)}"

enhanced_desc = generate_enhanced_description(
    image_url="https://saya.pk/cdn/shop/files/SP-6521_Ai-1.jpg?v=1740122840",
    text_description=None
)
print(enhanced_desc)