"""
Company settings routes for managing company information.
All company settings operations interact with MongoDB database.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
from bson import ObjectId
from datetime import datetime
from typing import Any

# Create a Blueprint for company settings routes
company_settings_bp = Blueprint('company_settings', __name__)


def convert_objectid_to_str(obj: Any) -> Any:
    """Convert ObjectId to string recursively and add 'id' field for compatibility."""
    if isinstance(obj, ObjectId):
        return str(obj)
    elif isinstance(obj, dict):
        converted = {k: convert_objectid_to_str(v) for k, v in obj.items()}
        # Add 'id' field mapped to '_id' for frontend compatibility
        if '_id' in converted and 'id' not in converted:
            converted['id'] = str(converted['_id'])
        return converted
    elif isinstance(obj, list):
        return [convert_objectid_to_str(item) for item in obj]
    return obj


@company_settings_bp.get("/api/company-settings")
def get_company_settings():
    """
    Get company settings.
    Returns the first company settings record (shared across all users).
    
    Returns:
        JSON object with company settings
    """
    try:
        collection = get_collection("company_settings")
        settings = collection.find_one()
        
        if not settings:
            return jsonify({}), 200
        
        settings = convert_objectid_to_str(settings)
        return jsonify(settings)
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch company settings: {error_msg}"}), 500


@company_settings_bp.post("/api/company-settings")
def create_company_settings():
    """
    Create company settings.
    
    Required fields:
        - user_id: UUID of the user creating the settings
        - company_name_en: Company name in English
        - company_name_ar: Company name in Arabic
        - phone: Phone number
        - vat_id: VAT ID
        - address_en: Address in English
        - address_ar: Address in Arabic
    
    Returns:
        Created company settings object with 201 status code
    """
    data = request.get_json(force=True) or {}
    
    try:
        collection = get_collection("company_settings")
        
        # Check if settings already exist
        existing = collection.find_one()
        if existing:
            return jsonify({"error": "Company settings already exist. Use PUT to update."}), 400
        
        # Prepare settings document
        settings_doc = {
            "user_id": data.get("user_id", ""),
            "company_name_en": data.get("company_name_en", ""),
            "company_name_ar": data.get("company_name_ar", ""),
            "phone": data.get("phone", ""),
            "vat_id": data.get("vat_id", ""),
            "address_en": data.get("address_en", ""),
            "address_ar": data.get("address_ar", ""),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Insert settings
        result = collection.insert_one(settings_doc)
        
        # Fetch the created settings
        created_settings = collection.find_one({"_id": result.inserted_id})
        created_settings = convert_objectid_to_str(created_settings)
        
        return jsonify(created_settings), 201
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({
            "error": f"Failed to create company settings: {error_msg}"
        }), 500


@company_settings_bp.put("/api/company-settings")
def update_company_settings():
    """
    Update company settings.
    Updates the first company settings record (shared across all users).
    
    Allowed fields to update:
        - company_name_en, company_name_ar
        - phone, vat_id
        - address_en, address_ar
    
    Returns:
        Updated company settings object
    """
    data = request.get_json(force=True) or {}
    
    # Only allow specific fields to be updated
    allowed = {
        "company_name_en", "company_name_ar",
        "phone", "vat_id",
        "address_en", "address_ar"
    }
    update = {k: data[k] for k in allowed if k in data}
    
    if not update:
        return jsonify({"error": "No valid fields to update"}), 400
    
    # Add updated_at timestamp
    update["updated_at"] = datetime.utcnow().isoformat()
    
    try:
        collection = get_collection("company_settings")
        
        # Find and update the first settings record
        result = collection.update_one(
            {},
            {"$set": update},
            upsert=False
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Company settings not found"}), 404
        
        # Fetch updated settings
        updated_settings = collection.find_one()
        updated_settings = convert_objectid_to_str(updated_settings)
        
        return jsonify(updated_settings)
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to update company settings: {error_msg}"}), 500
