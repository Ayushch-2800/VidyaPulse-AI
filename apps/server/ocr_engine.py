import os
import time
from PIL import Image
from typing import Dict, Any

from gemini_utils import CHAT_MODEL, base_config_options


# The client automatically picks up GEMINI_API_KEY from the environment
# Make sure it is loaded via dotenv or exported in the terminal
def extract_visual_data(image_path: str, timestamp: float) -> Dict[str, Any]:
    """
    Passes a visual keyframe to a VLM to extract text, LaTeX formulas, and code.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Keyframe not found at {image_path}")

    # Imported here so loading this module makes no Gemini setup
    from google import genai

    img = Image.open(image_path)
    client = genai.Client()

    prompt = """
    Analyze this educational video frame and extract the core information. 
    Strictly follow these formatting rules:
    1. Extract all readable text exactly as written.
    2. Convert any mathematical formulas, equations, or symbols into standard LaTeX markdown. Use single $for inline math and double$$ for block equations.
    3. If there is a programming code block, enclose it in standard markdown code fences (```).
    4. If there is a diagram or chart, provide a concise 1-2 sentence semantic description of what it represents.
    
    Output ONLY the extracted markdown content. Do not add conversational filler.
    """

    max_retries = 5
    extracted_text = ""

    for attempt in range(max_retries):
        try:
            # Same model as the chat engines, set with GEMINI_CHAT_MODEL
            response = client.models.generate_content(
                model=CHAT_MODEL,
                contents=[prompt, img],
                config=base_config_options(),
            )
            extracted_text = response.text.strip()
            break  # Success, exit the retry loop

        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                wait_time = (attempt + 1) * 5  # Waits 1s, then 2s
                print(f"[OCR WARNING] API busy (503). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"[OCR ERROR] Failed to process keyframe at {timestamp}s: {e}")
                break

    return {
        "timestamp": timestamp,
        "image_path": image_path,
        "extracted_content": extracted_text,
        "content_type": "visual_ocr",
    }


# --- TEST EXECUTION BLOCK ---
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()  # This ensures GEMINI_API_KEY is loaded from your .env file

    print("Testing OCR on test_frame.jpg...")

    try:
        # Run the extraction on the test image shown in your VS Code
        result = extract_visual_data("test_frame.jpg", 0.0)

        print("\n--- OCR EXTRACTION RESULT ---")
        print(result["extracted_content"])
    except Exception as e:
        print(f"\nTest failed: {e}")
