"""
Groq OCR Service — uses Llama 4 Scout vision model (via Groq API).
Logic ported from backend/Vision/app.py.
Supports: JPG, JPEG, PNG, WEBP, BMP, GIF, PDF (page-by-page via pdf2image).
"""
import base64
import io
import json
import mimetypes
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
PDF_EXTENSION = ".pdf"


def _get_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set")
    return Groq(api_key=api_key)


def _encode_bytes(data: bytes, mime_type: str) -> str:
    return base64.b64encode(data).decode("utf-8")


def _encode_file(file_path: Path) -> tuple[str, str]:
    """Return (base64_string, mime_type) for a file on disk."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if not mime_type:
        mime_type = "application/octet-stream"
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return b64, mime_type


EXTRACTION_PROMPT = """
Analyze this invoice/receipt image and extract all line items from the table.

For each item/row in the invoice table, extract:
- item_id: The item number, SKU, product code, or part number (alphanumeric codes like "ABC123", "P-001")
- item_name: The product/item description or name
- quantity: The quantity ordered/sold (numeric value, default to 1 if not visible)
- total_price: The LINE TOTAL from the LAST/RIGHTMOST column of the table (NOT the unit price)

Also extract at the end:
- company_name: The supplier/vendor company name
- vat_id: The VAT registration number if present
- invoice_total: The overall invoice grand total if present

Return ONLY a valid JSON object — no markdown, no code blocks:
{
    "items": [
        {
            "item_id": "string or empty string if not found",
            "item_name": "string",
            "quantity": number,
            "total_price": number
        }
    ],
    "company_name": "string",
    "vat_id": "string",
    "invoice_total": number,
    "raw_text": "Brief summary of the invoice content",
    "confidence": 0.0 to 1.0
}

Rules:
- Extract ALL visible line items
- If item_id/SKU not visible, use ""
- If quantity not visible, default to 1
- total_price MUST be from the last column (line total, not unit price)
- Numbers must be actual numbers, not strings
- Return ONLY valid JSON
"""


def _call_groq_image(client: Groq, b64: str, mime_type: str, prompt: str) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return response.choices[0].message.content or ""


def _parse_groq_response(raw: str) -> dict:
    """Strip markdown fences and parse JSON from Groq response."""
    text = raw.strip()
    for fence in ("```json", "```"):
        if text.startswith(fence):
            text = text[len(fence):]
    if text.endswith("```"):
        text = text[:-3]
    return json.loads(text.strip())


def _clean_result(result: dict) -> dict:
    cleaned_items = []
    for item in result.get("items", []):
        cleaned_items.append(
            {
                "item_id": str(item.get("item_id", "")).strip(),
                "item_name": str(item.get("item_name", "")).strip(),
                "quantity": int(float(item.get("quantity", 1))),
                "total_price": float(item.get("total_price", 0)),
            }
        )
    result["items"] = cleaned_items
    result["confidence"] = float(result.get("confidence", 0.8))
    result["raw_text"] = str(result.get("raw_text", ""))
    result["company_name"] = str(result.get("company_name", ""))
    result["vat_id"] = str(result.get("vat_id", ""))
    result.setdefault("invoice_total", None)
    return result


def process_invoice_image(file_path: str) -> dict:
    """
    OCR an invoice image (or PDF) using Groq Llama 4 Scout.

    Args:
        file_path: Path to a JPG/PNG/WEBP/BMP/GIF/PDF file.

    Returns:
        {items, company_name, vat_id, invoice_total, raw_text, confidence}
    """
    client = _get_client()
    path = Path(file_path)
    ext = path.suffix.lower()

    try:
        if ext == PDF_EXTENSION:
            return _process_pdf(client, path)

        if ext in IMAGE_EXTENSIONS:
            b64, mime = _encode_file(path)
            raw = _call_groq_image(client, b64, mime, EXTRACTION_PROMPT)
            result = _parse_groq_response(raw)
            return _clean_result(result)

        return {
            "items": [],
            "raw_text": "",
            "confidence": 0,
            "error": f"Unsupported file extension: {ext}",
        }

    except json.JSONDecodeError as e:
        return {"items": [], "raw_text": "", "confidence": 0, "parse_error": str(e)}
    except Exception as e:
        return {"items": [], "raw_text": "", "confidence": 0, "error": str(e)}


def _process_pdf(client: Groq, path: Path) -> dict:
    """Convert each PDF page to JPEG and OCR — mirrors Vision/app.py logic."""
    try:
        from pdf2image import convert_from_path
    except ImportError:
        return {
            "items": [],
            "raw_text": (
                "[PDF support requires pdf2image + poppler. "
                "Install: pip install pdf2image, then install poppler for your OS.]"
            ),
            "confidence": 0,
            "error": "pdf2image not installed",
        }

    pages = convert_from_path(str(path), dpi=200)
    all_items: list[dict] = []
    page_summaries: list[str] = []

    page_prompt = (
        "This is a page of a multi-page PDF invoice. "
        + EXTRACTION_PROMPT
    )

    for page_num, page_img in enumerate(pages, start=1):
        buf = io.BytesIO()
        page_img.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        raw = _call_groq_image(client, b64, "image/jpeg", page_prompt)
        try:
            result = _clean_result(_parse_groq_response(raw))
            all_items.extend(result.get("items", []))
            if result.get("raw_text"):
                page_summaries.append(f"Page {page_num}: {result['raw_text']}")
        except Exception:
            page_summaries.append(f"Page {page_num}: [parse error]")

    return {
        "items": all_items,
        "raw_text": " | ".join(page_summaries),
        "confidence": 0.8 if all_items else 0,
        "company_name": "",
        "vat_id": "",
        "invoice_total": None,
    }
