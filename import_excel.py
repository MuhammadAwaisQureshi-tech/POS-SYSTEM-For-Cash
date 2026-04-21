"""
Excel import utility for Supabase products table.

This script reads Excel files and imports product data into the Supabase database.
It handles batch insertion, data validation, and error handling.

Usage:
    python import_excel.py [path_to_excel_file] [user_id]

Example:
    python import_excel.py data/products.xlsx
    python import_excel.py data/products.xlsx 123e4567-e89b-12d3-a456-426614174000
"""
import os
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from supabase_client import get_supabase_client

# Load environment variables from multiple locations
# Try project root first, then backend directory
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env, override=True)

# Also try loading from current directory (if running from backend/)
load_dotenv(override=False)


def get_first_user_id(supabase):
    """
    Get the first user_id from the profiles table.
    This is used as a fallback when user_id is not provided.
    
    Args:
        supabase: Supabase client instance
    
    Returns:
        str: First user_id found, or None if no users exist
    """
    try:
        resp = supabase.table("profiles").select("id").limit(1).execute()
        if resp.data and len(resp.data) > 0:
            return resp.data[0]["id"]
    except Exception as e:
        print(f"Error getting user_id: {e}")
    return None


def get_column_value(row, possible_names, default=""):
    """
    Get a column value from a pandas row using case-insensitive matching.
    Handles variations in column names including case differences and extra spaces.
    
    Args:
        row: pandas Series (row from DataFrame)
        possible_names: list of possible column names (e.g., ["Category", "CATEGORY", "category"])
        default: default value if column not found
    
    Returns:
        str: Column value or default
    """
    # First try exact match
    for name in possible_names:
        if name in row.index:
            value = row.get(name, default)
            return str(value).strip() if pd.notna(value) else default
    
    # Try case-insensitive match (also handles spaces)
    row_columns_normalized = {col.strip().lower(): col for col in row.index}
    for name in possible_names:
        normalized_name = name.strip().lower()
        if normalized_name in row_columns_normalized:
            actual_col = row_columns_normalized[normalized_name]
            value = row.get(actual_col, default)
            return str(value).strip() if pd.notna(value) else default
    
    return default


def import_excel_to_supabase(excel_path, user_id=None):
    """
    Import Excel data to Supabase products table.
    
    This function reads an Excel file, validates the data, and imports it into
    the Supabase products table in batches for efficiency.
    
    Args:
        excel_path: Path to the Excel file to import
        user_id: Optional user_id to use for all products. If not provided,
                 will try to get from Excel file or Supabase profiles table.
    
    Excel columns expected:
        - Category: Product category (optional)
        - Item Name: Name of the item (optional)
        - Item_No: Item number/identifier (required)
        - Description: Product description (required)
        - Unit: Unit of measurement, e.g., "Piece", "Kg" (defaults to "Piece")
        - Quantity: Initial quantity (defaults to 0)
        - Unit_Price: Price per unit (defaults to 0)
        - Discount: Discount amount (defaults to 0)
        - VAT_Percent: VAT percentage (defaults to 15)
        - user_id: User ID (optional, can be in Excel or provided as parameter)
    
    Returns:
        bool: True if import was successful, False otherwise
    """
    print(f"Reading Excel file: {excel_path}")
    
    # Read Excel file
    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return False
    
    print(f"Found {len(df)} rows in Excel file")
    print(f"Columns: {df.columns.tolist()}")
    
    # Check for category column variations (for debugging)
    category_cols = [col for col in df.columns if col.lower() in ["category", "categories"]]
    if category_cols:
        print(f"Found category column(s): {category_cols}")
    else:
        print("Warning: No category column found (case-insensitive search)")
    
    # Get Supabase client
    try:
        supabase = get_supabase_client()
    except Exception as e:
        print(f"Error connecting to Supabase: {e}")
        return False
    
    # Check if Excel file has user_id column
    excel_has_user_id = "user_id" in df.columns
    
    # Get user_id if not provided
    if not user_id:
        if excel_has_user_id:
            # Use user_id from Excel (use first non-null value)
            user_ids = df["user_id"].dropna().unique()
            if len(user_ids) > 0:
                user_id = str(user_ids[0]).strip()
                print(f"Using user_id from Excel file: {user_id}")
                if len(user_ids) > 1:
                    print(f"Warning: Multiple user_ids found in Excel. Using first one: {user_id}")
            else:
                # Try to get from Supabase
                user_id = get_first_user_id(supabase)
                if not user_id:
                    print("ERROR: No user_id found in Excel or Supabase. Please provide user_id.")
                    return False
                print(f"Using user_id from Supabase: {user_id}")
        else:
            # Try to get from Supabase
            user_id = get_first_user_id(supabase)
            if not user_id:
                print("ERROR: No user_id found. Please create a user first or provide user_id.")
                return False
            print(f"Using user_id from Supabase: {user_id}")
    
    # Prepare data for insertion
    products = []
    skipped = 0
    
    for idx, row in df.iterrows():
        try:
            # Get user_id for this row (from Excel if available, otherwise use default)
            row_user_id = str(row.get("user_id", user_id)).strip() if excel_has_user_id else user_id
            
            # Map columns (handle case-insensitive and variations)
            # Use helper function for case-insensitive column matching
            category_value = get_column_value(row, ["Category", "CATEGORY", "category", "Categories"], "")
            item_name_value = get_column_value(row, ["Item Name", "Item_Name", "item_name", "Item name"], "")
            item_no_value = get_column_value(row, ["Item_No", "Item No", "item_no", "ITEM_NO"], "")
            description_value = get_column_value(row, ["Description", "description", "DESCRIPTION"], "")
            unit_value = get_column_value(row, ["Unit", "unit", "UNIT"], "Piece")
            quantity_value = get_column_value(row, ["Quantity", "quantity", "QUANTITY"], "0")
            unit_price_value = get_column_value(row, ["Unit_Price", "Unit Price", "unit_price", "UNIT_PRICE"], "0")
            discount_value = get_column_value(row, ["Discount", "discount", "DISCOUNT"], "0")
            vat_percent_value = get_column_value(row, ["VAT_Percent", "VAT Percent", "vat_percent", "VAT_PERCENT", "VAT%"], "15")
            
            product = {
                "user_id": row_user_id,
                "item_no": item_no_value,
                "description": description_value,
                "item_name": item_name_value or None,
                "category": category_value or None,
                "unit": unit_value or "Piece",
                "quantity": int(quantity_value or 0),
                "unit_price": float(unit_price_value or 0),
                "discount": float(discount_value or 0),
                "vat_percent": float(vat_percent_value or 15)
            }
            
            # Validate required fields
            if not product["item_no"] or not product["description"]:
                print(f"Row {idx + 2}: Skipping - missing item_no or description")
                skipped += 1
                continue
            
            products.append(product)
        except Exception as e:
            print(f"Row {idx + 2}: Error processing - {e}")
            skipped += 1
            continue
    
    if not products:
        print("No valid products to import!")
        return False
    
    print(f"\nPrepared {len(products)} products for import (skipped {skipped} rows)")
    
    # Insert in batches for efficiency
    # Supabase allows up to 1000 rows per insert, but we use 100 for better error handling
    batch_size = 100
    total_inserted = 0
    
    for i in range(0, len(products), batch_size):
        batch = products[i:i + batch_size]
        try:
            resp = supabase.table("products").insert(batch).execute()
            if resp.data:
                total_inserted += len(resp.data)
                print(f"Inserted batch {i//batch_size + 1}: {len(resp.data)} products")
            else:
                print(f"Warning: Batch {i//batch_size + 1} returned no data")
        except Exception as e:
            print(f"Error inserting batch {i//batch_size + 1}: {e}")
            # Try inserting one by one for this batch
            for product in batch:
                try:
                    resp = supabase.table("products").insert(product).execute()
                    if resp.data:
                        total_inserted += 1
                except Exception as e2:
                    print(f"  Failed to insert {product.get('item_no')}: {e2}")
    
    print(f"\n✅ Import complete! {total_inserted} products imported successfully.")
    return True


if __name__ == "__main__":
    """
    Main entry point for the Excel import script.
    Handles command-line arguments and executes the import.
    """
    # Default Excel file path (in data folder)
    excel_file = Path(__file__).parent / "data" / "New Microsoft Excel Worksheet (2).xlsx"
    
    # Allow custom path via command line argument
    if len(sys.argv) > 1:
        excel_file = Path(sys.argv[1])
    
    # Validate that the Excel file exists
    if not excel_file.exists():
        print(f"ERROR: Excel file not found: {excel_file}")
        print(f"Usage: python import_excel.py [path_to_excel_file] [user_id]")
        sys.exit(1)
    
    # Optional: provide user_id as second command-line argument
    user_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Execute the import
    success = import_excel_to_supabase(excel_file, user_id)
    sys.exit(0 if success else 1)

