"""
Invoice routes for managing invoices.
All invoice operations interact with MongoDB database.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
from zatca_qr import generate_zatca_qr, format_amount, format_datetime
from datetime import datetime
from bson import ObjectId
from typing import Any
import json

# Create a Blueprint for invoice routes
invoices_bp = Blueprint('invoices', __name__)


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


def update_product_quantities(items):
    """
    Update product quantities in inventory after invoice is created.
    Deducts the sold quantity from each product's inventory.
    
    Args:
        items: List of invoice items, each containing product_id and quantity
    
    Returns:
        tuple: (success: bool, errors: list)
    """
    if not items or not isinstance(items, list):
        return True, []
    
    errors = []
    collection = get_collection("products")
    
    for item in items:
        try:
            product_id = item.get("product_id")
            sold_quantity = item.get("quantity", 0)
            
            if not product_id:
                errors.append(f"Item missing product_id: {item}")
                continue
            
            if sold_quantity <= 0:
                # Skip items with zero or negative quantity
                continue
            
            # Try to find product by MongoDB _id first, then by id field
            try:
                # Try ObjectId format
                obj_id = ObjectId(product_id)
                current_product = collection.find_one({"_id": obj_id})
            except:
                # Try string id field
                current_product = collection.find_one({"id": product_id})
                if not current_product:
                    # Also try _id as string
                    current_product = collection.find_one({"_id": product_id})
            
            if not current_product:
                errors.append(f"Product not found: {product_id}")
                continue
            
            current_quantity = int(current_product.get("quantity", 0))
            
            # Calculate new quantity (ensure it doesn't go below 0)
            new_quantity = max(0, current_quantity - sold_quantity)
            
            # Update product quantity in MongoDB
            try:
                obj_id = ObjectId(product_id)
                update_result = collection.update_one(
                    {"_id": obj_id},
                    {"$set": {"quantity": new_quantity, "updated_at": datetime.utcnow().isoformat()}}
                )
            except:
                # Try updating by id field or _id as string
                update_result = collection.update_one(
                    {"$or": [{"id": product_id}, {"_id": product_id}]},
                    {"$set": {"quantity": new_quantity, "updated_at": datetime.utcnow().isoformat()}}
                )
            
            if update_result.matched_count == 0:
                errors.append(f"Failed to update product {product_id}")
                
        except Exception as e:
            error_msg = f"Error updating product {item.get('product_id', 'unknown')}: {str(e)}"
            errors.append(error_msg)
    
    return len(errors) == 0, errors


@invoices_bp.post("/api/invoices")
def create_invoice():
    """
    Create a new invoice in MongoDB.
    
    Required fields:
        - invoice_no: Invoice number
        - customer_name: Name of the customer
        - items: List of invoice items (JSON array)
        - total_amount: Total invoice amount (must be a number)
    
    Optional fields:
        - user_id: User ID (optional, for multi-user support)
        - customer_phone: Customer phone number
        - customer_vat_id: Customer VAT ID
        - customer_address: Customer address
        - quotation_price: Quotation price type
        - subtotal: Subtotal amount (defaults to 0)
        - discount: Discount amount (defaults to 0)
        - vat_amount: VAT amount (defaults to 0)
        - currency: Currency code (defaults to "SAR" for Saudi Riyal)
        - notes: Additional notes for the invoice
        - receiver_name: Receiver name
        - cashier_name: Cashier name
    
    Returns:
        Created invoice object with 201 status code
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Extract and validate required fields
    invoice_no = (payload or {}).get("invoice_no")
    customer_name = (payload or {}).get("customer_name")
    items = (payload or {}).get("items", [])
    total_amount = (payload or {}).get("total_amount")
    
    # Get user_id from payload - required for tracking which user created the invoice
    user_id = (payload or {}).get("user_id", "")
    
    # Validate user_id is provided
    if not user_id:
        return jsonify({"error": "user_id is required. Please ensure you are logged in."}), 400
    customer_phone = (payload or {}).get("customer_phone", "")
    customer_vat_id = (payload or {}).get("customer_vat_id", "")
    customer_address = (payload or {}).get("customer_address", "")
    quotation_price = (payload or {}).get("quotation_price", "")
    subtotal = (payload or {}).get("subtotal", 0.0)
    discount = (payload or {}).get("discount", 0.0)
    vat_amount = (payload or {}).get("vat_amount", 0.0)
    currency = (payload or {}).get("currency", "SAR")
    notes = (payload or {}).get("notes", "")
    receiver_name = (payload or {}).get("receiver_name", "")
    cashier_name = (payload or {}).get("cashier_name", "")

    # Validate required fields
    if not invoice_no:
        return jsonify({"error": "invoice_no is required"}), 400
    if not customer_name:
        return jsonify({"error": "customer_name is required"}), 400
    if not items or not isinstance(items, list):
        return jsonify({"error": "items must be a non-empty array"}), 400
    
    # Validate and convert amounts
    try:
        total_amount = float(total_amount) if total_amount is not None else 0.0
        subtotal = float(subtotal) if subtotal is not None else 0.0
        discount = float(discount) if discount is not None else 0.0
        vat_amount = float(vat_amount) if vat_amount is not None else 0.0
    except (TypeError, ValueError):
        return jsonify({"error": "Amounts must be valid numbers"}), 400

    # Prepare invoice document for MongoDB
    now = datetime.utcnow()
    invoice_doc = {
        "invoice_no": invoice_no,
        "user_id": user_id,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_vat_id": customer_vat_id,
        "customer_address": customer_address,
        "quotation_price": quotation_price,
        "items": items,  # Store as array in MongoDB (no need to JSON stringify)
        "subtotal": subtotal,
        "discount": discount,
        "vat_amount": vat_amount,
        "total": total_amount,
        "total_amount": total_amount,  # Keep both for compatibility
        "currency": currency,
        "notes": notes,
        "receiver_name": receiver_name,
        "cashier_name": cashier_name,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }

    try:
        collection = get_collection("invoices")
        
        # Insert invoice into MongoDB
        result = collection.insert_one(invoice_doc)
        
        if not result.inserted_id:
            return jsonify({"error": "Failed to create invoice"}), 500

        # Fetch the created invoice
        created_invoice = collection.find_one({"_id": result.inserted_id})
        
        # Save customer information for future use
        try:
            if customer_name:  # Only save if customer name is provided
                customers_collection = get_collection("customers")
                now_iso = now.isoformat()
                
                # Check if customer already exists
                existing_customer = customers_collection.find_one({
                    "customer_name": customer_name,
                    "user_id": user_id
                })
                
                customer_doc = {
                    "user_id": user_id,
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "customer_vat_id": customer_vat_id,
                    "customer_address": customer_address,
                    "updated_at": now_iso
                }
                
                if existing_customer:
                    # Update existing customer
                    customers_collection.update_one(
                        {"_id": existing_customer.get("_id")},
                        {"$set": customer_doc}
                    )
                else:
                    # Insert new customer
                    customer_doc["created_at"] = now_iso
                    customers_collection.insert_one(customer_doc)
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Error saving customer information: {str(e)}")
        
        # Update product quantities in inventory after invoice is saved
        try:
            success, errors = update_product_quantities(items)
            if not success and errors:
                # Log errors but don't fail the invoice creation
                print(f"Warning: Some product quantities could not be updated: {errors}")
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Error updating product quantities: {str(e)}")

        # Generate ZATCA QR code
        try:
            # ZATCA Phase-1 required data
            seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
            vat_number = "314265267200003"
            invoice_datetime = format_datetime(now)
            total_amount_str = format_amount(total_amount)
            vat_amount_str = format_amount(vat_amount)
            
            qr_code = generate_zatca_qr(
                seller_name=seller_name,
                vat_number=vat_number,
                invoice_datetime=invoice_datetime,
                total_amount=total_amount_str,
                vat_amount=vat_amount_str
            )
            
            # Update invoice with QR code
            collection.update_one(
                {"_id": result.inserted_id},
                {"$set": {"qr_code": qr_code}}
            )
            created_invoice["qr_code"] = qr_code
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Failed to generate QR code: {str(e)}")
            created_invoice["qr_code"] = None

        # Convert ObjectId to string and add 'id' field
        created_invoice = convert_objectid_to_str(created_invoice)
        
        return jsonify(created_invoice), 201
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to create invoice: {error_msg}"}), 500


@invoices_bp.get("/api/invoices")
def list_invoices():
    """
    Get all invoices from MongoDB.
    Returns invoices ordered by creation date (newest first).
    Each invoice includes ZATCA QR code.
    
    Returns:
        JSON array of invoice objects
    """
    try:
        collection = get_collection("invoices")
        invoices = list(collection.find().sort("created_at", -1))
        
        # ZATCA Phase-1 required data (fixed for this company)
        seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
        vat_number = "314265267200003"
        
        result = []
        for invoice in invoices:
            invoice_dict = convert_objectid_to_str(invoice)
            
            # Generate QR code for each invoice if not already present
            if not invoice_dict.get("qr_code"):
                try:
                    created_at = datetime.fromisoformat(invoice_dict.get("created_at", "").replace("Z", ""))
                    invoice_datetime = format_datetime(created_at)
                    total_amount_str = format_amount(float(invoice_dict.get("total", invoice_dict.get("total_amount", 0))))
                    vat_amount_str = format_amount(float(invoice_dict.get("vat_amount", 0)))
                    
                    qr_code = generate_zatca_qr(
                        seller_name=seller_name,
                        vat_number=vat_number,
                        invoice_datetime=invoice_datetime,
                        total_amount=total_amount_str,
                        vat_amount=vat_amount_str
                    )
                    invoice_dict["qr_code"] = qr_code
                except Exception as e:
                    print(f"Warning: Failed to generate QR code for invoice {invoice_dict.get('id')}: {str(e)}")
                    invoice_dict["qr_code"] = None
            
            result.append(invoice_dict)
        
        return jsonify(result)
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch invoices: {error_msg}"}), 500


@invoices_bp.get("/api/invoices/<invoice_id>/qr")
def get_invoice_qr(invoice_id):
    """
    Get ZATCA QR code for a specific invoice.
    
    Args:
        invoice_id: ID of the invoice (MongoDB ObjectId string)
        
    Returns:
        JSON object with qr_code field, or error with 404
    """
    try:
        collection = get_collection("invoices")
        
        # Try to find invoice by ObjectId
        try:
            obj_id = ObjectId(invoice_id)
            invoice = collection.find_one({"_id": obj_id})
        except:
            # Try finding by id field or _id as string
            invoice = collection.find_one({"$or": [{"id": invoice_id}, {"_id": invoice_id}]})
        
        if not invoice:
            return jsonify({"error": "Invoice not found"}), 404

        try:
            # ZATCA Phase-1 required data
            seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
            vat_number = "314265267200003"
            created_at = datetime.fromisoformat(invoice.get("created_at", "").replace("Z", ""))
            invoice_datetime = format_datetime(created_at)
            total_amount = float(invoice.get("total", invoice.get("total_amount", 0)))
            vat_amount = float(invoice.get("vat_amount", 0))
            total_amount_str = format_amount(total_amount)
            vat_amount_str = format_amount(vat_amount)
            
            qr_code = generate_zatca_qr(
                seller_name=seller_name,
                vat_number=vat_number,
                invoice_datetime=invoice_datetime,
                total_amount=total_amount_str,
                vat_amount=vat_amount_str
            )
            
            invoice_id_str = str(invoice.get("_id", invoice_id))
            invoice_no = invoice.get("invoice_no", "")
            
            return jsonify({
                "invoice_id": invoice_id_str,
                "invoice_no": invoice_no,
                "qr_code": qr_code
            })
        except Exception as e:
            return jsonify({"error": f"Failed to generate QR code: {str(e)}"}), 500
            
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch invoice: {error_msg}"}), 500


@invoices_bp.delete("/api/invoices/<invoice_id>")
def delete_invoice(invoice_id):
    """
    Delete an invoice by ID.
    
    Args:
        invoice_id: ID of the invoice to delete (MongoDB ObjectId string)
    
    Returns:
        Success message with 200 status code, or error with 404/500
    """
    try:
        collection = get_collection("invoices")
        
        # Try to find and delete by ObjectId
        try:
            obj_id = ObjectId(invoice_id)
            result = collection.delete_one({"_id": obj_id})
        except:
            # Try deleting by id field or _id as string
            result = collection.delete_one({"$or": [{"id": invoice_id}, {"_id": invoice_id}]})
        
        if result.deleted_count == 0:
            return jsonify({"error": "Invoice not found"}), 404
        
        return jsonify({"message": "Invoice deleted successfully"}), 200
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to delete invoice: {error_msg}"}), 500


@invoices_bp.post("/api/invoices-cash")
def create_invoice_cash():
    """
    Create a new invoice in the InvoicesCash MongoDB collection.
    This endpoint stores invoices separately for cash transactions.
    
    Required fields:
        - invoice_no: Invoice number
        - customer_name: Name of the customer
        - items: List of invoice items (JSON array)
        - total_amount: Total invoice amount (must be a number)
    
    Optional fields:
        - user_id: User ID (optional, for multi-user support)
        - customer_phone: Customer phone number
        - customer_vat_id: Customer VAT ID
        - customer_address: Customer address
        - quotation_price: Quotation price type
        - subtotal: Subtotal amount (defaults to 0)
        - discount: Discount amount (defaults to 0)
        - vat_amount: VAT amount (defaults to 0)
        - currency: Currency code (defaults to "SAR" for Saudi Riyal)
        - notes: Additional notes for the invoice
        - receiver_name: Receiver name
        - cashier_name: Cashier name
    
    Returns:
        Created invoice object with 201 status code
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Extract and validate required fields
    invoice_no = (payload or {}).get("invoice_no")
    customer_name = (payload or {}).get("customer_name")
    items = (payload or {}).get("items", [])
    total_amount = (payload or {}).get("total_amount")
    
    # Get user_id from payload - required for tracking which user created the invoice
    user_id = (payload or {}).get("user_id", "")
    
    # Validate user_id is provided
    if not user_id:
        return jsonify({"error": "user_id is required. Please ensure you are logged in."}), 400
    customer_phone = (payload or {}).get("customer_phone", "")
    customer_vat_id = (payload or {}).get("customer_vat_id", "")
    customer_address = (payload or {}).get("customer_address", "")
    quotation_price = (payload or {}).get("quotation_price", "")
    subtotal = (payload or {}).get("subtotal", 0.0)
    discount = (payload or {}).get("discount", 0.0)
    vat_amount = (payload or {}).get("vat_amount", 0.0)
    currency = (payload or {}).get("currency", "SAR")
    notes = (payload or {}).get("notes", "")
    receiver_name = (payload or {}).get("receiver_name", "")
    cashier_name = (payload or {}).get("cashier_name", "")

    # Validate required fields
    if not invoice_no:
        return jsonify({"error": "invoice_no is required"}), 400
    if not customer_name:
        return jsonify({"error": "customer_name is required"}), 400
    if not items or not isinstance(items, list):
        return jsonify({"error": "items must be a non-empty array"}), 400
    
    # Validate and convert amounts
    try:
        total_amount = float(total_amount) if total_amount is not None else 0.0
        subtotal = float(subtotal) if subtotal is not None else 0.0
        discount = float(discount) if discount is not None else 0.0
        vat_amount = float(vat_amount) if vat_amount is not None else 0.0
    except (TypeError, ValueError):
        return jsonify({"error": "Amounts must be valid numbers"}), 400

    # Prepare invoice document for MongoDB
    now = datetime.utcnow()
    invoice_doc = {
        "invoice_no": invoice_no,
        "user_id": user_id,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_vat_id": customer_vat_id,
        "customer_address": customer_address,
        "quotation_price": quotation_price,
        "items": items,  # Store as array in MongoDB (no need to JSON stringify)
        "subtotal": subtotal,
        "discount": discount,
        "vat_amount": vat_amount,
        "total": total_amount,
        "total_amount": total_amount,  # Keep both for compatibility
        "currency": currency,
        "notes": notes,
        "receiver_name": receiver_name,
        "cashier_name": cashier_name,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }

    try:
        # Use InvoicesCash collection instead of invoices
        collection = get_collection("InvoicesCash")
        
        # Insert invoice into MongoDB
        result = collection.insert_one(invoice_doc)
        
        if not result.inserted_id:
            return jsonify({"error": "Failed to create invoice"}), 500

        # Fetch the created invoice
        created_invoice = collection.find_one({"_id": result.inserted_id})
        
        # Save customer information for future use
        try:
            if customer_name:  # Only save if customer name is provided
                customers_collection = get_collection("customers")
                now_iso = now.isoformat()
                
                # Check if customer already exists
                existing_customer = customers_collection.find_one({
                    "customer_name": customer_name,
                    "user_id": user_id
                })
                
                customer_doc = {
                    "user_id": user_id,
                    "customer_name": customer_name,
                    "customer_phone": customer_phone,
                    "customer_vat_id": customer_vat_id,
                    "customer_address": customer_address,
                    "updated_at": now_iso
                }
                
                if existing_customer:
                    # Update existing customer
                    customers_collection.update_one(
                        {"_id": existing_customer.get("_id")},
                        {"$set": customer_doc}
                    )
                else:
                    # Insert new customer
                    customer_doc["created_at"] = now_iso
                    customers_collection.insert_one(customer_doc)
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Error saving customer information: {str(e)}")
        
        # Update product quantities in inventory after invoice is saved
        try:
            success, errors = update_product_quantities(items)
            if not success and errors:
                # Log errors but don't fail the invoice creation
                print(f"Warning: Some product quantities could not be updated: {errors}")
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Error updating product quantities: {str(e)}")

        # Generate ZATCA QR code
        try:
            # ZATCA Phase-1 required data
            seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
            vat_number = "314265267200003"
            invoice_datetime = format_datetime(now)
            total_amount_str = format_amount(total_amount)
            vat_amount_str = format_amount(vat_amount)
            
            qr_code = generate_zatca_qr(
                seller_name=seller_name,
                vat_number=vat_number,
                invoice_datetime=invoice_datetime,
                total_amount=total_amount_str,
                vat_amount=vat_amount_str
            )
            
            # Update invoice with QR code
            collection.update_one(
                {"_id": result.inserted_id},
                {"$set": {"qr_code": qr_code}}
            )
            created_invoice["qr_code"] = qr_code
        except Exception as e:
            # Log error but don't fail the invoice creation
            print(f"Warning: Failed to generate QR code: {str(e)}")
            created_invoice["qr_code"] = None

        # Convert ObjectId to string and add 'id' field
        created_invoice = convert_objectid_to_str(created_invoice)
        
        return jsonify(created_invoice), 201
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to create invoice: {error_msg}"}), 500


@invoices_bp.get("/api/invoices-cash")
def list_invoices_cash():
    """
    Get all invoices from the InvoicesCash MongoDB collection.
    Returns invoices ordered by creation date (newest first).
    Each invoice includes ZATCA QR code.
    
    Returns:
        JSON array of invoice objects
    """
    try:
        collection = get_collection("InvoicesCash")
        invoices = list(collection.find().sort("created_at", -1))
        
        # ZATCA Phase-1 required data (fixed for this company)
        seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
        vat_number = "314265267200003"
        
        result = []
        for invoice in invoices:
            invoice_dict = convert_objectid_to_str(invoice)
            
            # Generate QR code for each invoice if not already present
            if not invoice_dict.get("qr_code"):
                try:
                    created_at = datetime.fromisoformat(invoice_dict.get("created_at", "").replace("Z", ""))
                    invoice_datetime = format_datetime(created_at)
                    total_amount_str = format_amount(float(invoice_dict.get("total", invoice_dict.get("total_amount", 0))))
                    vat_amount_str = format_amount(float(invoice_dict.get("vat_amount", 0)))
                    
                    qr_code = generate_zatca_qr(
                        seller_name=seller_name,
                        vat_number=vat_number,
                        invoice_datetime=invoice_datetime,
                        total_amount=total_amount_str,
                        vat_amount=vat_amount_str
                    )
                    invoice_dict["qr_code"] = qr_code
                except Exception as e:
                    print(f"Warning: Failed to generate QR code for invoice {invoice_dict.get('id')}: {str(e)}")
                    invoice_dict["qr_code"] = None
            
            result.append(invoice_dict)
        
        return jsonify(result)
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch invoices: {error_msg}"}), 500


@invoices_bp.delete("/api/invoices-cash/<invoice_id>")
def delete_invoice_cash(invoice_id):
    """
    Delete an invoice from InvoicesCash collection by ID.
    
    Args:
        invoice_id: ID of the invoice to delete (MongoDB ObjectId string)
    
    Returns:
        Success message with 200 status code, or error with 404/500
    """
    try:
        collection = get_collection("InvoicesCash")
        
        # Try to find and delete by ObjectId
        try:
            obj_id = ObjectId(invoice_id)
            result = collection.delete_one({"_id": obj_id})
        except:
            # Try deleting by id field or _id as string
            result = collection.delete_one({"$or": [{"id": invoice_id}, {"_id": invoice_id}]})
        
        if result.deleted_count == 0:
            return jsonify({"error": "Invoice not found"}), 404
        
        return jsonify({"message": "Invoice deleted successfully"}), 200
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to delete invoice: {error_msg}"}), 500
