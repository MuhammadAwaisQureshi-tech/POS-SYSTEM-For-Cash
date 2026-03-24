"""
Account Analysis routes for managing daily account records.
All account analysis operations interact with MongoDB database.
"""
import os
from flask import Blueprint, request, jsonify, Response
from werkzeug.utils import secure_filename
from mongodb_client import get_collection
from bson import ObjectId
from bson.binary import Binary
from datetime import datetime
from typing import Any, Optional, Tuple

# Invoice files stored as BSON Binary on the document (MongoDB doc limit 16MB).
MAX_PURCHASE_INVOICE_BYTES = 10 * 1024 * 1024
ALLOWED_INVOICE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}

# Create a Blueprint for account analysis routes
account_analysis_bp = Blueprint('account_analysis', __name__)


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


def daily_record_to_json(doc: Optional[dict]) -> Optional[dict]:
    """Serialize a daily record for JSON responses (never embed binary file data)."""
    if doc is None:
        return None
    d = dict(doc)
    has_invoice = bool(d.get("purchase_invoice_data"))
    d.pop("purchase_invoice_data", None)
    d = convert_objectid_to_str(d)
    d["has_purchase_invoice"] = has_invoice
    return d


def _parse_invoice_upload(file_storage) -> Optional[dict]:
    """Validate and read uploaded invoice file; returns fields for $set or None if no file."""
    if file_storage is None or file_storage.filename is None or file_storage.filename.strip() == "":
        return None
    data = file_storage.read()
    if len(data) > MAX_PURCHASE_INVOICE_BYTES:
        raise ValueError(f"Invoice file too large (max {MAX_PURCHASE_INVOICE_BYTES // (1024 * 1024)}MB)")
    ext = os.path.splitext(file_storage.filename)[1].lower()
    if ext not in ALLOWED_INVOICE_EXTENSIONS:
        raise ValueError(
            "Invalid invoice file type. Allowed: " + ", ".join(sorted(ALLOWED_INVOICE_EXTENSIONS))
        )
    safe_name = secure_filename(file_storage.filename) or "invoice"
    return {
        "purchase_invoice_filename": safe_name,
        "purchase_invoice_content_type": file_storage.content_type or "application/octet-stream",
        "purchase_invoice_data": Binary(data),
    }


def _load_daily_record(collection, record_id: str) -> Tuple[Any, Optional[dict]]:
    """Resolve ObjectId and return (obj_id, doc) or (None, None) if not found."""
    try:
        obj_id = ObjectId(record_id)
    except Exception:
        return None, None
    record = collection.find_one({"_id": obj_id})
    if not record:
        return None, None
    return obj_id, record


@account_analysis_bp.post("/api/account-analysis/daily-record")
def create_daily_record():
    """
    Create a new daily account record.
    
    Required fields:
        - user_id: User ID creating the record
        - date: Date of the record (YYYY-MM-DD format)
        - total_cash_sale: Total cash sales amount
        - total_bank: Total bank amount
        - total_purchase_amount: Total purchase amount
        - purchase_company_name: Name of the purchase company
    
    Optional fields:
        - notes: Additional notes or comments
    
    Returns:
        Created daily record object with 201 status code
    
    Accepts application/json or multipart/form-data (use field name purchase_invoice for the file).
    """
    payload = {}
    invoice_file = None
    # Use mimetype (normalized lowercase); substring match on content_type fails for
    # "Multipart/form-data" from some clients/browsers.
    if request.mimetype == "multipart/form-data":
        payload = {k: request.form.get(k) for k in request.form}
        invoice_file = request.files.get("purchase_invoice")
    else:
        try:
            payload = request.get_json(force=True) or {}
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

    # Extract and validate required fields
    user_id = payload.get("user_id")
    date_str = payload.get("date")
    total_cash_sale = payload.get("total_cash_sale")
    total_bank = payload.get("total_bank")
    total_purchase_amount = payload.get("total_purchase_amount")
    purchase_company_name = payload.get("purchase_company_name")
    notes = payload.get("notes") or ""
    company_phone = (payload.get("company_phone") or "").strip()

    # Validate required fields
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400
    if not date_str:
        return jsonify({"error": "date is required"}), 400
    if total_cash_sale is None:
        return jsonify({"error": "total_cash_sale is required"}), 400
    if total_bank is None:
        return jsonify({"error": "total_bank is required"}), 400
    if total_purchase_amount is None:
        return jsonify({"error": "total_purchase_amount is required"}), 400
    if not purchase_company_name:
        return jsonify({"error": "purchase_company_name is required"}), 400

    # Validate and convert amounts
    try:
        total_cash_sale = float(total_cash_sale)
        total_bank = float(total_bank)
        total_purchase_amount = float(total_purchase_amount)
    except (TypeError, ValueError):
        return jsonify({"error": "Amounts must be valid numbers"}), 400

    # Parse date
    try:
        record_date = datetime.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    # Prepare daily record document
    now = datetime.utcnow()
    daily_record_doc = {
        "user_id": user_id,
        "date": record_date.strftime("%Y-%m-%d"),
        "total_cash_sale": total_cash_sale,
        "total_bank": total_bank,
        "total_purchase_amount": total_purchase_amount,
        "purchase_company_name": purchase_company_name,
        "company_phone": company_phone,
        "notes": notes,
        "purchase_invoice_filename": None,
        "purchase_invoice_content_type": None,
        "purchase_invoice_data": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    try:
        if invoice_file is not None:
            inv = _parse_invoice_upload(invoice_file)
            if inv:
                daily_record_doc.update(inv)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    try:
        collection = get_collection("account_analysis_daily")
        
        # Insert daily record
        result = collection.insert_one(daily_record_doc)
        
        if not result.inserted_id:
            return jsonify({"error": "Failed to create daily record"}), 500

        # Fetch the created record
        created_record = collection.find_one({"_id": result.inserted_id})
        
        return jsonify(daily_record_to_json(created_record)), 201
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to create daily record: {error_msg}"}), 500


@account_analysis_bp.get("/api/account-analysis/daily-records")
def list_daily_records():
    """
    Get all daily account records.
    Returns records ordered by date (newest first).
    
    Query parameters:
        - user_id: Filter by user ID (optional)
        - start_date: Filter by start date (YYYY-MM-DD, optional)
        - end_date: Filter by end date (YYYY-MM-DD, optional)
    
    Returns:
        JSON array of daily record objects
    """
    try:
        collection = get_collection("account_analysis_daily")
        
        # Build filter query
        filter_query = {}
        
        # Filter by user_id if provided
        user_id = request.args.get("user_id")
        if user_id:
            filter_query["user_id"] = user_id
        
        # Filter by date range if provided
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        
        if start_date or end_date:
            filter_query["date"] = {}
            if start_date:
                filter_query["date"]["$gte"] = start_date
            if end_date:
                filter_query["date"]["$lte"] = end_date
        
        # Fetch records
        cursor = collection.find(filter_query).sort("date", -1)
        records = list(cursor)
        
        records = [daily_record_to_json(r) for r in records]
        
        return jsonify(records)
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch daily records: {error_msg}"}), 500


@account_analysis_bp.get("/api/account-analysis/daily-records/<record_id>")
def get_daily_record(record_id):
    """
    Get a specific daily record by ID.
    
    Args:
        record_id: ID of the daily record (MongoDB ObjectId string)
    
    Returns:
        JSON object with daily record, or error with 404
    """
    try:
        collection = get_collection("account_analysis_daily")
        
        # Try to find record by ObjectId
        try:
            obj_id = ObjectId(record_id)
            record = collection.find_one({"_id": obj_id})
        except:
            # Try finding by id field
            record = collection.find_one({"$or": [{"id": record_id}, {"_id": record_id}]})
        
        if not record:
            return jsonify({"error": "Daily record not found"}), 404
        
        return jsonify(daily_record_to_json(record))
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch daily record: {error_msg}"}), 500


@account_analysis_bp.get("/api/account-analysis/daily-records/<record_id>/purchase-invoice")
def download_purchase_invoice(record_id):
    """Download the stored purchase invoice file (binary from MongoDB)."""
    try:
        collection = get_collection("account_analysis_daily")
        obj_id, record = _load_daily_record(collection, record_id)
        if not record:
            return jsonify({"error": "Daily record not found"}), 404
        raw = record.get("purchase_invoice_data")
        if not raw:
            return jsonify({"error": "No purchase invoice attached"}), 404
        filename = record.get("purchase_invoice_filename") or "invoice"
        ctype = record.get("purchase_invoice_content_type") or "application/octet-stream"
        # raw may be Binary or bytes
        data = bytes(raw) if raw is not None else b""
        return Response(
            data,
            mimetype=ctype,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, max-age=0",
            },
        )
    except Exception as e:
        return jsonify({"error": f"Failed to download invoice: {str(e)}"}), 500


@account_analysis_bp.post("/api/account-analysis/daily-records/<record_id>/purchase-invoice")
def upload_purchase_invoice(record_id):
    """Attach or replace the purchase invoice on an existing daily record."""
    try:
        if "file" not in request.files:
            return jsonify({"error": "file is required"}), 400
        inv = _parse_invoice_upload(request.files["file"])
        if not inv:
            return jsonify({"error": "No file selected"}), 400
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    try:
        collection = get_collection("account_analysis_daily")
        obj_id, record = _load_daily_record(collection, record_id)
        if not record:
            return jsonify({"error": "Daily record not found"}), 404
        inv["updated_at"] = datetime.utcnow().isoformat()
        collection.update_one({"_id": obj_id}, {"$set": inv})
        updated = collection.find_one({"_id": obj_id})
        return jsonify(daily_record_to_json(updated)), 200
    except Exception as e:
        return jsonify({"error": f"Failed to upload invoice: {str(e)}"}), 500


@account_analysis_bp.put("/api/account-analysis/daily-records/<record_id>")
def update_daily_record(record_id):
    """
    Update an existing daily record by ID.
    
    Args:
        record_id: ID of the daily record to update
    
    Allowed fields to update:
        - total_cash_sale, total_bank, total_purchase_amount
        - purchase_company_name, company_phone, notes
    
    Returns:
        Updated daily record object
    """
    try:
        data = request.get_json(force=True) or {}
        
        # Only allow specific fields to be updated
        allowed = {
            "total_cash_sale", "total_bank", "total_purchase_amount",
            "purchase_company_name", "company_phone", "notes"
        }
        update = {k: data[k] for k in allowed if k in data}
        if "company_phone" in update and update["company_phone"] is not None:
            update["company_phone"] = str(update["company_phone"]).strip()
        
        if not update:
            return jsonify({"error": "No valid fields to update"}), 400
        
        # Coerce numeric fields to proper types
        for k in ("total_cash_sale", "total_bank", "total_purchase_amount"):
            if k in update and update[k] is not None:
                update[k] = float(update[k])
        
        # Add updated_at timestamp
        update["updated_at"] = datetime.utcnow().isoformat()
        
        collection = get_collection("account_analysis_daily")
        
        # Convert string ID to ObjectId
        try:
            obj_id = ObjectId(record_id)
        except:
            return jsonify({"error": "Invalid record ID format"}), 400
        
        # Update record
        result = collection.update_one(
            {"_id": obj_id},
            {"$set": update}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "Daily record not found"}), 404
        
        # Fetch updated record
        updated_record = collection.find_one({"_id": obj_id})
        
        return jsonify(daily_record_to_json(updated_record))
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to update daily record: {error_msg}"}), 500


@account_analysis_bp.delete("/api/account-analysis/daily-records/<record_id>")
def delete_daily_record(record_id):
    """
    Delete a daily record by ID.
    
    Args:
        record_id: ID of the daily record to delete
    
    Returns:
        Success message with 200 status code, or error with 404/500
    """
    try:
        collection = get_collection("account_analysis_daily")
        
        # Convert string ID to ObjectId
        try:
            obj_id = ObjectId(record_id)
        except:
            return jsonify({"error": "Invalid record ID format"}), 400
        
        # Delete record
        result = collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 0:
            return jsonify({"error": "Daily record not found"}), 404
        
        return jsonify({"message": "Daily record deleted successfully"}), 200
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to delete daily record: {error_msg}"}), 500


@account_analysis_bp.get("/api/account-analysis/summary")
def get_account_summary():
    """
    Get account analysis summary with aggregated statistics.
    
    Query parameters:
        - user_id: Filter by user ID (optional)
        - start_date: Filter by start date (YYYY-MM-DD, optional)
        - end_date: Filter by end date (YYYY-MM-DD, optional)
        - group_by: Group results by 'day', 'week', 'month', or 'company' (default: 'day')
    
    Returns:
        JSON object with summary statistics
    """
    try:
        collection = get_collection("account_analysis_daily")
        
        # Build match stage
        match_stage = {}
        
        user_id = request.args.get("user_id")
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        group_by = request.args.get("group_by", "day")
        
        if user_id:
            match_stage["user_id"] = user_id
        
        if start_date or end_date:
            match_stage["date"] = {}
            if start_date:
                match_stage["date"]["$gte"] = start_date
            if end_date:
                match_stage["date"]["$lte"] = end_date
        
        # Build aggregation pipeline
        pipeline = []
        
        # Match stage
        if match_stage:
            pipeline.append({"$match": match_stage})
        
        # Group stage based on group_by parameter
        if group_by == "company":
            # Group by company
            pipeline.append({
                "$group": {
                    "_id": "$purchase_company_name",
                    "total_cash_sale": {"$sum": "$total_cash_sale"},
                    "total_bank": {"$sum": "$total_bank"},
                    "total_purchase_amount": {"$sum": "$total_purchase_amount"},
                    "record_count": {"$sum": 1}
                }
            })
        elif group_by == "month":
            # Group by month
            pipeline.append({
                "$group": {
                    "_id": {"$substr": ["$date", 0, 7]},  # YYYY-MM
                    "total_cash_sale": {"$sum": "$total_cash_sale"},
                    "total_bank": {"$sum": "$total_bank"},
                    "total_purchase_amount": {"$sum": "$total_purchase_amount"},
                    "record_count": {"$sum": 1}
                }
            })
        elif group_by == "week":
            # Group by week (ISO week)
            pipeline.append({
                "$group": {
                    "_id": {
                        "year": {"$year": {"$dateFromString": {"dateString": "$date"}}},
                        "week": {"$week": {"$dateFromString": {"dateString": "$date"}}}
                    },
                    "total_cash_sale": {"$sum": "$total_cash_sale"},
                    "total_bank": {"$sum": "$total_bank"},
                    "total_purchase_amount": {"$sum": "$total_purchase_amount"},
                    "record_count": {"$sum": 1}
                }
            })
        else:  # day (default)
            # Group by day
            pipeline.append({
                "$group": {
                    "_id": "$date",
                    "total_cash_sale": {"$sum": "$total_cash_sale"},
                    "total_bank": {"$sum": "$total_bank"},
                    "total_purchase_amount": {"$sum": "$total_purchase_amount"},
                    "record_count": {"$sum": 1}
                }
            })
        
        # Sort stage
        pipeline.append({"$sort": {"_id": -1}})
        
        # Execute aggregation
        result = list(collection.aggregate(pipeline))
        
        # Convert ObjectId to string
        result = convert_objectid_to_str(result)
        
        # Calculate overall totals
        overall_totals = {
            "total_cash_sale": sum(r.get("total_cash_sale", 0) for r in result),
            "total_bank": sum(r.get("total_bank", 0) for r in result),
            "total_purchase_amount": sum(r.get("total_purchase_amount", 0) for r in result),
            "net_balance": sum(r.get("total_cash_sale", 0) + r.get("total_bank", 0) - r.get("total_purchase_amount", 0) for r in result)
        }
        
        return jsonify({
            "records": result,
            "overall_totals": overall_totals,
            "group_by": group_by
        })
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch account summary: {error_msg}"}), 500
