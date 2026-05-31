"""
OCR routes — invoice image/PDF processing via Groq Llama 4 Scout vision model.
"""
from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
import os
import tempfile
from mongodb_client import get_collection
from bson import ObjectId

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from services.groq_ocr import process_invoice_image

ocr_bp = Blueprint('ocr', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def convert_objectid_to_str(obj):
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        converted = {k: convert_objectid_to_str(v) for k, v in obj.items()}
        if '_id' in converted and 'id' not in converted:
            converted['id'] = str(converted['_id'])
        return converted
    elif isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    return obj


@ocr_bp.post("/api/ocr/upload")
def upload_and_process():
    """
    Upload a file and process with Groq OCR (Llama 4 Scout).

    Request: multipart/form-data
        - file:    Image (PNG/JPG/JPEG/WEBP/BMP/GIF) or PDF
        - user_id: User identifier

    Response:
        {
            "success": true,
            "items": [...],
            "raw_text": "...",
            "confidence": 0.95,
            "company_name": "...",
            "vat_id": "..."
        }
    """
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400

    file = request.files['file']
    user_id = request.form.get('user_id')

    if not user_id:
        return jsonify({"success": False, "error": "user_id is required"}), 400

    if not file.filename:
        return jsonify({"success": False, "error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": f"File type not allowed. Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        }), 400

    file.seek(0, 2)
    size = file.tell()
    file.seek(0)

    if size > MAX_FILE_SIZE:
        return jsonify({
            "success": False,
            "error": f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB"
        }), 400

    filename = secure_filename(file.filename)
    file_ext = os.path.splitext(filename)[1].lower()

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            file.save(tmp.name)
            temp_path = tmp.name

        ocr_result = process_invoice_image(temp_path)

        if "error" in ocr_result or "parse_error" in ocr_result:
            error_msg = ocr_result.get("error") or ocr_result.get("parse_error")
            return jsonify({
                "success": False,
                "error": f"OCR processing failed: {error_msg}",
                "raw_text": ocr_result.get("raw_text", "")
            }), 500

        # Match extracted items against products in DB
        products_collection = get_collection("products")
        matched_items = []

        for item in ocr_result.get("items", []):
            item_id = item.get("item_id", "").strip()
            item_name = item.get("item_name", "").strip()
            quantity = item.get("quantity", 1)
            total_price = item.get("total_price", 0)

            matched_product = None
            match_status = "not_found"

            if item_id:
                product = products_collection.find_one({"item_no": item_id})
                if not product:
                    product = products_collection.find_one(
                        {"item_no": {"$regex": f"^{item_id}$", "$options": "i"}}
                    )
                if product:
                    product = convert_objectid_to_str(product)
                    matched_product = {
                        "id": product.get("id") or str(product.get("_id")),
                        "item_no": product.get("item_no"),
                        "item_name": product.get("item_name") or product.get("description"),
                        "description": product.get("description"),
                        "unit_price": float(product.get("unit_price", 0)),
                        "quantity": int(product.get("quantity", 0)),
                        "vat_percent": float(product.get("vat_percent", 15)),
                        "unit": product.get("unit", "Piece"),
                    }
                    match_status = "matched"

            matched_items.append({
                "item_id": item_id,
                "item_name": item_name,
                "quantity": quantity,
                "total_price": total_price,
                "matched_product": matched_product,
                "match_status": match_status,
            })

        return jsonify({
            "success": True,
            "items": matched_items,
            "raw_text": ocr_result.get("raw_text", ""),
            "confidence": ocr_result.get("confidence", 0),
            "company_name": ocr_result.get("company_name", ""),
            "vat_id": ocr_result.get("vat_id", ""),
            "invoice_total": ocr_result.get("invoice_total"),
        }), 200

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": f"OCR processing failed: {str(e)}"}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
