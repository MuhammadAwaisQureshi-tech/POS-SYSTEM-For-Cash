"""
Product routes for managing inventory products.
All product operations interact with MongoDB database.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
from bson import ObjectId
from datetime import datetime
from typing import Dict, Any

# Create a Blueprint for product routes
products_bp = Blueprint('products', __name__)


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


@products_bp.get("/api/products")
def list_products():
    """
    Get all products from the database.
    Returns all products shared across all users, ordered by creation date (newest first).
    
    Returns:
        JSON array of product objects
    """
    try:
        collection = get_collection("products")
        products = list(collection.find().sort("created_at", -1))
        
        # Convert ObjectId to string
        products = convert_objectid_to_str(products)
        
        return jsonify(products or [])
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch products: {error_msg}"}), 500


@products_bp.post("/api/products")
def create_product():
    """
    Create a new product in the database.
    
    Required fields:
        - user_id: UUID of the user creating the product
        - item_no: Item number/identifier
        - description: Product description
        - unit: Unit of measurement (e.g., "Piece", "Kg")
        - quantity: Initial quantity
        - unit_price: Price per unit
    
    Optional fields:
        - item_name: Name of the item
        - category: Product category
        - discount: Discount amount
        - vat_percent: VAT percentage
    
    Returns:
        Created product object with 201 status code
    """
    data = request.get_json(force=True) or {}
    
    # Validate required fields
    required = ["user_id", "item_no", "description", "unit", "quantity", "unit_price"]
    missing = [k for k in required if data.get(k) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing required fields: {', '.join(missing)}"}), 400
    
    try:
        collection = get_collection("products")
        
        # Prepare product document
        product_doc = {
            "user_id": data["user_id"],
            "item_no": data["item_no"],
            "item_name": data.get("item_name") or "",
            "description": data["description"],
            "category": data.get("category") or "",
            "unit": data["unit"],
            "quantity": int(data.get("quantity", 0)),
            "unit_price": float(data.get("unit_price", 0)),
            "discount": float(data.get("discount", 0) or 0),
            "vat_percent": float(data.get("vat_percent", 0) or 0),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Insert product
        result = collection.insert_one(product_doc)
        
        # Fetch the created product
        created_product = collection.find_one({"_id": result.inserted_id})
        created_product = convert_objectid_to_str(created_product)
        
        return jsonify(created_product), 201
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({
            "error": f"Failed to create product: {error_msg}"
        }), 500


@products_bp.put("/api/products/<product_id>")
def update_product(product_id: str):
    """
    Update an existing product by ID.
    
    Args:
        product_id: ID of the product to update
    
    Allowed fields to update:
        - item_no, item_name, description, category
        - unit, quantity, unit_price, discount, vat_percent
    
    Returns:
        Updated product object
    """
    data = request.get_json(force=True) or {}
    
    # Only allow specific fields to be updated
    allowed = {
        "item_no", "item_name", "description", "category",
        "unit", "quantity", "unit_price", "discount", "vat_percent"
    }
    update = {k: data[k] for k in allowed if k in data}
    
    if not update:
        return jsonify({"error": "No valid fields to update"}), 400
    
    # Coerce numeric fields to proper types
    for k in ("unit_price", "discount", "vat_percent"):
        if k in update and update[k] is not None:
            update[k] = float(update[k])
    
    # Quantity must be integer, not float
    if "quantity" in update and update["quantity"] is not None:
        update["quantity"] = int(update["quantity"])
    
    # Add updated_at timestamp
    update["updated_at"] = datetime.utcnow().isoformat()
    
    try:
        collection = get_collection("products")
        
        # Convert string ID to ObjectId
        try:
            obj_id = ObjectId(product_id)
        except:
            return jsonify({"error": "Invalid product ID format"}), 400
        
        # Update product
        result = collection.update_one(
            {"_id": obj_id},
            {"$set": update}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Product not found"}), 404
        
        # Fetch updated product
        updated_product = collection.find_one({"_id": obj_id})
        updated_product = convert_objectid_to_str(updated_product)
        
        return jsonify(updated_product)
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to update product: {error_msg}"}), 500


@products_bp.delete("/api/products/<product_id>")
def delete_product(product_id: str):
    """
    Delete a product by ID.
    
    Args:
        product_id: ID of the product to delete
    
    Returns:
        Empty response with 204 status code on success
    """
    try:
        collection = get_collection("products")
        
        # Convert string ID to ObjectId
        try:
            obj_id = ObjectId(product_id)
        except:
            return jsonify({"error": "Invalid product ID format"}), 400
        
        # Delete product
        result = collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 0:
            return jsonify({"error": "Product not found"}), 404
        
        return ("", 204)
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to delete product: {error_msg}"}), 500
