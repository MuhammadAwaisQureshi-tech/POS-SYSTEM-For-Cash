"""
Debug routes for development and troubleshooting.
These endpoints should be removed or secured in production.
"""
from flask import Blueprint, request, jsonify
import os
from supabase_client import get_supabase_client

# Create a Blueprint for debug routes
debug_bp = Blueprint('debug', __name__)


@debug_bp.get("/api/health")
def health():
    """
    Health check endpoint to verify the API is running.
    
    Returns:
        JSON object with status "ok"
    """
    return {"status": "ok"}


@debug_bp.get("/api/debug/supabase-config")
def debug_supabase_config():
    """
    Debug endpoint to check Supabase configuration.
    This helps troubleshoot connection and authentication issues.
    
    WARNING: Remove this endpoint in production or secure it properly.
    
    Returns:
        JSON object with Supabase configuration details
    """
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    
    config = {
        "supabase_url_set": bool(url),
        "supabase_url": url if url else None,
        "service_key_set": bool(service_key),
        "service_key_preview": service_key[:20] + "..." if service_key else None,
        "service_key_starts_with_eyJ": service_key.startswith("eyJ") if service_key else False,
        "key_length": len(service_key) if service_key else 0,
    }
    
    # Check if it looks like anon key (shorter, different format)
    if service_key:
        if len(service_key) < 100:
            config["warning"] = "Service key appears too short. Make sure you're using SERVICE_ROLE key, not anon key."
        elif not service_key.startswith("eyJ"):
            config["warning"] = "Service key format looks incorrect. Should start with 'eyJ'"
    
    return jsonify(config)


@debug_bp.get("/api/debug/test-insert")
def debug_test_insert():
    """
    Test endpoint to verify service_role permissions.
    Attempts to insert a test record to check if RLS (Row Level Security) is properly configured.
    
    WARNING: Remove this endpoint in production or secure it properly.
    
    Returns:
        JSON object with test results
    """
    try:
        supabase_client = get_supabase_client()
        
        # Try to insert a test record to check permissions
        test_record = {
            "user_id": "123e4567-e89b-12d3-a456-426614174000",
            "item_no": "TEST-001",
            "description": "Test Product",
            "unit": "Piece",
            "quantity": 1,
            "unit_price": 1.00,
        }
        resp = supabase_client.table("products").insert(test_record).execute()
        
        return jsonify({
            "status": "success",
            "message": "Service role has proper permissions!",
            "data": resp.data[0] if resp.data else None
        })
    except Exception as e:
        error_msg = str(e)
        return jsonify({
            "status": "error",
            "message": "Permission test failed",
            "error": error_msg,
            "solution": "Run the SQL fix in data/fix_permissions.sql or see information/HOW_TO_FIX_RLS_ERROR.md"
        }), 500


@debug_bp.get("/api/debug/test-purchase-products-insert")
def debug_test_purchase_products_insert():
    """
    Test endpoint to verify service_role permissions for purchase_products table.
    Attempts to insert a test record to check if RLS (Row Level Security) is properly configured.
    
    WARNING: Remove this endpoint in production or secure it properly.
    
    Returns:
        JSON object with test results
    """
    try:
        supabase_client = get_supabase_client()
        
        # First check if table exists
        try:
            check_resp = supabase_client.table("purchase_products").select("id").limit(1).execute()
        except Exception as table_error:
            return jsonify({
                "status": "error",
                "message": "Table does not exist or is not accessible",
                "error": str(table_error),
                "solution": "Run the SQL script: backend/display_file/COMPLETE_PURCHASE_PRODUCTS_SETUP.sql"
            }), 500
        
        # Try to insert a test record to check permissions
        test_record = {
            "user_id": "123e4567-e89b-12d3-a456-426614174000",
            "item_no": "TEST-PURCHASE-001",
            "description": "Test Purchase Product",
            "unit": "Piece",
            "quantity": 1,
            "unit_price": 1.00,
        }
        resp = supabase_client.table("purchase_products").insert(test_record).execute()
        
        return jsonify({
            "status": "success",
            "message": "Service role has proper permissions for purchase_products!",
            "data": resp.data[0] if resp.data else None
        })
    except Exception as e:
        error_msg = str(e)
        is_rls_error = "row-level security" in error_msg.lower() or "42501" in error_msg or "permission denied" in error_msg.lower()
        return jsonify({
            "status": "error",
            "message": "Permission test failed for purchase_products",
            "error": error_msg,
            "is_rls_error": is_rls_error,
            "solution": "Run the SQL script: backend/display_file/COMPLETE_PURCHASE_PRODUCTS_SETUP.sql in Supabase SQL Editor"
        }), 500
