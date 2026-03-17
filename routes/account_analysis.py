"""
Account Analysis routes for managing daily account records.
All account analysis operations interact with MongoDB database.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Any
from collections import defaultdict

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
    """
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    # Extract and validate required fields
    user_id = payload.get("user_id")
    date_str = payload.get("date")
    total_cash_sale = payload.get("total_cash_sale")
    total_bank = payload.get("total_bank")
    total_purchase_amount = payload.get("total_purchase_amount")
    purchase_company_name = payload.get("purchase_company_name")
    notes = payload.get("notes", "")

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
        "notes": notes,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat()
    }

    try:
        collection = get_collection("account_analysis_daily")
        
        # Insert daily record
        result = collection.insert_one(daily_record_doc)
        
        if not result.inserted_id:
            return jsonify({"error": "Failed to create daily record"}), 500

        # Fetch the created record
        created_record = collection.find_one({"_id": result.inserted_id})
        created_record = convert_objectid_to_str(created_record)
        
        return jsonify(created_record), 201
        
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
        
        # Convert ObjectId to string
        records = convert_objectid_to_str(records)
        
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
        
        # Convert ObjectId to string
        record = convert_objectid_to_str(record)
        
        return jsonify(record)
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch daily record: {error_msg}"}), 500


@account_analysis_bp.put("/api/account-analysis/daily-records/<record_id>")
def update_daily_record(record_id):
    """
    Update an existing daily record by ID.
    
    Args:
        record_id: ID of the daily record to update
    
    Allowed fields to update:
        - total_cash_sale, total_bank, total_purchase_amount
        - purchase_company_name, notes
    
    Returns:
        Updated daily record object
    """
    try:
        data = request.get_json(force=True) or {}
        
        # Only allow specific fields to be updated
        allowed = {
            "total_cash_sale", "total_bank", "total_purchase_amount",
            "purchase_company_name", "notes"
        }
        update = {k: data[k] for k in allowed if k in data}
        
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
        updated_record = convert_objectid_to_str(updated_record)
        
        return jsonify(updated_record)
        
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
