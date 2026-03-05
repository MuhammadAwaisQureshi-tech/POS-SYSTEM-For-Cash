"""
Customer routes for managing customer information.
All customer operations interact with MongoDB database.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any

# Create a Blueprint for customer routes
customers_bp = Blueprint('customers', __name__)


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


@customers_bp.post("/api/customers")
def save_customer():
    """
    Save or update customer information.
    If customer with same name and user_id exists, update it.
    Otherwise, create a new customer record.
    
    Required fields:
        - user_id: User ID
        - customer_name: Customer name
    
    Optional fields:
        - customer_phone: Customer phone number
        - customer_vat_id: Customer VAT ID
        - customer_address: Customer address
    
    Returns:
        Customer object with 201 status code
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    
    # Extract fields
    user_id = payload.get("user_id", "")
    customer_name = payload.get("customer_name", "").strip()
    customer_phone = payload.get("customer_phone", "").strip()
    customer_vat_id = payload.get("customer_vat_id", "").strip()
    customer_address = payload.get("customer_address", "").strip()
    
    # Validate required fields
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not customer_name:
        return jsonify({"error": "customer_name is required"}), 400
    
    try:
        collection = get_collection("customers")
        now = datetime.utcnow().isoformat()
        
        # Check if customer already exists (by name and user_id)
        existing_customer = collection.find_one({
            "customer_name": customer_name,
            "user_id": user_id
        })
        
        customer_doc = {
            "user_id": user_id,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "customer_vat_id": customer_vat_id,
            "customer_address": customer_address,
            "updated_at": now
        }
        
        if existing_customer:
            # Update existing customer
            customer_id = existing_customer.get("_id")
            result = collection.update_one(
                {"_id": customer_id},
                {"$set": customer_doc}
            )
            
            if result.matched_count > 0:
                # Fetch updated customer
                updated_customer = collection.find_one({"_id": customer_id})
                updated_customer = convert_objectid_to_str(updated_customer)
                return jsonify(updated_customer), 200
            else:
                return jsonify({"error": "Failed to update customer"}), 500
        else:
            # Insert new customer
            customer_doc["created_at"] = now
            result = collection.insert_one(customer_doc)
            
            if result.inserted_id:
                # Fetch created customer
                new_customer = collection.find_one({"_id": result.inserted_id})
                new_customer = convert_objectid_to_str(new_customer)
                return jsonify(new_customer), 201
            else:
                return jsonify({"error": "Failed to create customer"}), 500
                
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to save customer: {error_msg}"}), 500


@customers_bp.get("/api/customers/last")
def get_last_customer():
    """
    Get the last used customer for a specific user.
    
    Query parameters:
        - user_id: User ID (required)
    
    Returns:
        Last customer object or empty object if none found
    """
    try:
        user_id = request.args.get("user_id", "")
        
        if not user_id:
            return jsonify({"error": "user_id query parameter is required"}), 400
        
        collection = get_collection("customers")
        
        # Find the most recently updated customer for this user
        last_customer = collection.find_one(
            {"user_id": user_id},
            sort=[("updated_at", -1)]  # Sort by updated_at descending
        )
        
        if last_customer:
            last_customer = convert_objectid_to_str(last_customer)
            return jsonify(last_customer), 200
        else:
            return jsonify({}), 200  # Return empty object if no customer found
            
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to get last customer: {error_msg}"}), 500


@customers_bp.get("/api/customers")
def list_customers():
    """
    Get all customers for a specific user.
    Optionally search by customer name.
    
    Query parameters:
        - user_id: User ID (required)
        - name: Customer name to search (optional, case-insensitive partial match)
    
    Returns:
        List of customer objects
    """
    try:
        user_id = request.args.get("user_id", "")
        name_query = request.args.get("name", "").strip()
        
        if not user_id:
            return jsonify({"error": "user_id query parameter is required"}), 400
        
        collection = get_collection("customers")
        
        # Build query
        query = {"user_id": user_id}
        
        # If name is provided, search for customers with matching name (case-insensitive)
        if name_query:
            query["customer_name"] = {"$regex": name_query, "$options": "i"}
        
        # Find customers matching query, sorted by most recently updated
        customers = list(collection.find(query).sort("updated_at", -1))
        
        customers = convert_objectid_to_str(customers)
        return jsonify(customers or []), 200
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch customers: {error_msg}"}), 500


@customers_bp.get("/api/customers/search")
def search_customer_by_name():
    """
    Search for a customer by exact name match.
    Returns the first matching customer.
    
    Query parameters:
        - user_id: User ID (required)
        - name: Customer name to search (required, exact match)
    
    Returns:
        Customer object or empty object if not found
    """
    try:
        user_id = request.args.get("user_id", "")
        customer_name = request.args.get("name", "").strip()
        
        if not user_id:
            return jsonify({"error": "user_id query parameter is required"}), 400
        if not customer_name:
            return jsonify({"error": "name query parameter is required"}), 400
        
        collection = get_collection("customers")
        
        # Find customer by exact name match (case-insensitive)
        customer = collection.find_one({
            "user_id": user_id,
            "customer_name": {"$regex": f"^{customer_name}$", "$options": "i"}
        })
        
        if customer:
            customer = convert_objectid_to_str(customer)
            return jsonify(customer), 200
        else:
            return jsonify({}), 200  # Return empty object if not found
            
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to search customer: {error_msg}"}), 500


@customers_bp.get("/api/customers/by-vat-id")
def get_customer_by_vat_id():
    """
    Get a customer by exact VAT ID match.
    
    Query parameters:
        - user_id: User ID (required)
        - vat_id: Customer VAT ID to search (required, exact match)
    
    Returns:
        Customer object or empty object if not found
    """
    try:
        user_id = request.args.get("user_id", "")
        vat_id = request.args.get("vat_id", "").strip()
        
        if not user_id:
            return jsonify({"error": "user_id query parameter is required"}), 400
        if not vat_id:
            return jsonify({"error": "vat_id query parameter is required"}), 400
        
        collection = get_collection("customers")
        
        # Find customer by exact VAT ID match
        customer = collection.find_one({
            "user_id": user_id,
            "customer_vat_id": vat_id
        })
        
        if customer:
            customer = convert_objectid_to_str(customer)
            return jsonify(customer), 200
        else:
            return jsonify({}), 200  # Return empty object if not found
            
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to search customer by VAT ID: {error_msg}"}), 500
