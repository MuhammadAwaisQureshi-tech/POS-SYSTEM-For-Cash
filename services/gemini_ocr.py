"""
Gemini OCR Service
Processes invoice images using Google Gemini API for text extraction.
"""
import os
import json
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini API
api_key = os.getenv("GEMINI_API_KEY")
if api_key:
    genai.configure(api_key=api_key)


def process_invoice_image(file_path: str) -> dict:
    """
    Process an invoice image using Google Gemini for OCR.

    Args:
        file_path: Path to the image file (PNG, JPG, JPEG)

    Returns:
        Dictionary with extracted items and metadata
    """
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set")

    # Upload file to Gemini
    uploaded_file = genai.upload_file(file_path)

    # Create model - using gemini-2.0-flash for fast processing
    model = genai.GenerativeModel("gemini-3-flash-preview")

    # Prompt for structured extraction
    prompt = """
    Analyze this invoice/receipt image and extract all line items from the table.

    For each item/row in the invoice table, extract:
    - item_id: The item number, SKU, product code, or part number (usually in the first column, look for alphanumeric codes like "ABC123", "P-001", etc.)
    - item_name: The product/item description or name
    - quantity: The quantity ordered/sold (numeric value, default to 1 if not visible)
    - total_price: The LINE TOTAL from the LAST/RIGHTMOST column of the table (this is the total price for this line item, NOT the unit price)

    IMPORTANT: The total_price should be extracted from the LAST COLUMN (rightmost) of the invoice table.
    This is typically labeled "Total", "Amount", "Line Total", "المجموع", or similar.
    Do NOT use the unit price column - use the final calculated total for each line.

    Return the data as a JSON object with this exact structure:
    {
        "items": [
            {
                "item_id": "string or empty string if not found",
                "item_name": "string",
                "quantity": number,
                "total_price": number
            }
        ],
        "raw_text": "Brief summary of the invoice content",
        "confidence": 0.0 to 1.0 based on extraction quality
    }

    Important rules:
    - Extract ALL visible items/rows from the invoice table
    - If item_id/SKU is not visible, use empty string ""
    - If quantity is not visible, default to 1
    - total_price MUST be from the last/rightmost column (the line total, not unit price)
    - Return ONLY valid JSON, no markdown code blocks or formatting
    - Numbers should be actual numbers, not strings
    """

    # Generate response
    response = model.generate_content([prompt, uploaded_file])

    # Parse response
    try:
        # Clean response text (remove markdown code blocks if present)
        response_text = response.text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]

        result = json.loads(response_text.strip())

        # Ensure items array exists
        if "items" not in result:
            result["items"] = []

        # Clean up items - ensure proper types
        cleaned_items = []
        for item in result.get("items", []):
            cleaned_item = {
                "item_id": str(item.get("item_id", "")).strip(),
                "item_name": str(item.get("item_name", "")).strip(),
                "quantity": int(float(item.get("quantity", 1))),
                "total_price": float(item.get("total_price", 0))
            }
            cleaned_items.append(cleaned_item)

        result["items"] = cleaned_items
        result["confidence"] = float(result.get("confidence", 0.8))
        result["raw_text"] = str(result.get("raw_text", ""))

        return result

    except json.JSONDecodeError as e:
        # Return error info if JSON parsing fails
        return {
            "items": [],
            "raw_text": response.text[:500] if response.text else "",
            "confidence": 0,
            "parse_error": str(e)
        }
    except Exception as e:
        return {
            "items": [],
            "raw_text": "",
            "confidence": 0,
            "error": str(e)
        }
