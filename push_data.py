"""
Excel to Purchase Products Table Update Script

This script reads Excel files from the data1 folder and updates the purchase_products collection
in MongoDB. It will update existing purchase products (matched by item_no and user_id) or
insert new ones if they don't exist.

Expected Excel columns:
    - user_id: User ID (UUID)
    - category: Product category
    - Item_No: Item number/identifier
    - Description: Product description
    - Unit: Unit of measurement (e.g., "Piece", "Kg")
    - Quantity: Product quantity
    - Unit_Price: Price per unit
    - Discount: Discount amount
    - VAT_Percent: VAT percentage
    - VAT: VAT amount (calculated field, not stored)
    - Amount: Total amount (calculated field, not stored)

Usage:
    python push_data.py [data1_folder_path] [user_id]

Example:
    python push_data.py
    python push_data.py ../data1
    python push_data.py ../data1 123e4567-e89b-12d3-a456-426614174000
"""
import os
import sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
from mongodb_client import get_collection
from datetime import datetime

# Load environment variables from multiple locations
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env, override=True)

load_dotenv(override=False)


def get_first_user_id():
    """
    Get the first user_id from the users collection.
    This is used as a fallback when user_id is not provided.
    
    Returns:
        str: First user_id found, or None if no users exist
    """
    try:
        collection = get_collection("users")
        user = collection.find_one()
        if user:
            return user.get("id") or str(user.get("_id", ""))
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


def find_product_by_item_no(item_no, user_id):
    """
    Find a purchase product by item_no and user_id.
    
    Args:
        item_no: Item number to search for
        user_id: User ID to match
    
    Returns:
        dict: Purchase product data if found, None otherwise
    """
    try:
        collection = get_collection("purchase_products")
        product = collection.find_one({"item_no": item_no, "user_id": user_id})
        return product
    except Exception as e:
        print(f"Error finding purchase product: {e}")
    return None


def update_or_insert_product(product_data, existing_product=None):
    """
    Update an existing purchase product or insert a new one.
    
    Args:
        product_data: Dictionary with purchase product data to update/insert
        existing_product: Existing purchase product data if found, None otherwise
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        collection = get_collection("purchase_products")
        
        # Add timestamps
        now = datetime.utcnow().isoformat()
        
        if existing_product:
            # Update existing purchase product
            product_id = existing_product.get("_id")
            product_data["updated_at"] = now
            result = collection.update_one(
                {"_id": product_id},
                {"$set": product_data}
            )
            if result.modified_count > 0 or result.matched_count > 0:
                return True
            else:
                print(f"  Warning: Update returned no matches for item_no: {product_data.get('item_no')}")
                return False
        else:
            # Insert new purchase product
            product_data["created_at"] = now
            product_data["updated_at"] = now
            result = collection.insert_one(product_data)
            if result.inserted_id:
                return True
            else:
                print(f"  Warning: Insert returned no ID for item_no: {product_data.get('item_no')}")
                return False
    except Exception as e:
        print(f"  Error updating/inserting purchase product: {e}")
        return False


def process_excel_file(excel_path, default_user_id=None):
    """
    Process a single Excel file and update purchase_products collection.
    
    Args:
        excel_path: Path to the Excel file
        default_user_id: Default user_id to use if not found in Excel
    
    Returns:
        tuple: (success_count, error_count, skipped_count)
    """
    print(f"\n{'='*60}")
    print(f"Processing: {excel_path}")
    print(f"{'='*60}")
    
    # Read Excel file
    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return (0, 1, 0)
    
    print(f"Found {len(df)} rows in Excel file")
    print(f"Columns: {df.columns.tolist()}")
    
    # Check if Excel file has user_id column
    excel_has_user_id = any(col.lower() in ["user_id", "user id"] for col in df.columns)
    
    # Get default user_id if not provided
    if not default_user_id:
        if excel_has_user_id:
            # Use user_id from Excel (use first non-null value)
            user_id_col = [col for col in df.columns if col.lower() in ["user_id", "user id"]][0]
            user_ids = df[user_id_col].dropna().unique()
            if len(user_ids) > 0:
                default_user_id = str(user_ids[0]).strip()
                print(f"Using user_id from Excel file: {default_user_id}")
                if len(user_ids) > 1:
                    print(f"Warning: Multiple user_ids found in Excel. Using first one: {default_user_id}")
            else:
                # Try to get from MongoDB
                default_user_id = get_first_user_id()
                if not default_user_id:
                    print("ERROR: No user_id found in Excel or MongoDB. Please provide user_id.")
                    return (0, len(df), 0)
                print(f"Using user_id from MongoDB: {default_user_id}")
        else:
            # Try to get from MongoDB
            default_user_id = get_first_user_id()
            if not default_user_id:
                print("ERROR: No user_id found. Please create a user first or provide user_id.")
                return (0, len(df), 0)
            print(f"Using user_id from MongoDB: {default_user_id}")
    
    # Process each row
    success_count = 0
    error_count = 0
    skipped_count = 0
    
    for idx, row in df.iterrows():
        try:
            # Get user_id for this row
            if excel_has_user_id:
                user_id_col = [col for col in df.columns if col.lower() in ["user_id", "user id"]][0]
                row_user_id = str(row.get(user_id_col, default_user_id)).strip() if pd.notna(row.get(user_id_col)) else default_user_id
            else:
                row_user_id = default_user_id
            
            # Map columns (handle case-insensitive and variations)
            category_value = get_column_value(row, ["category", "Category", "CATEGORY"], "")
            item_no_value = get_column_value(row, ["Item_No", "Item No", "item_no", "ITEM_NO", "ItemNo"], "")
            description_value = get_column_value(row, ["Description", "description", "DESCRIPTION"], "")
            unit_value = get_column_value(row, ["Unit", "unit", "UNIT"], "Piece")
            quantity_value = get_column_value(row, ["Quantity", "quantity", "QUANTITY"], "0")
            unit_price_value = get_column_value(row, ["Unit_Price", "Unit Price", "unit_price", "UNIT_PRICE", "UnitPrice"], "0")
            discount_value = get_column_value(row, ["Discount", "discount", "DISCOUNT"], "0")
            vat_percent_value = get_column_value(row, ["VAT_Percent", "VAT Percent", "vat_percent", "VAT_PERCENT", "VAT%", "VatPercent"], "15")
            
            # Validate required fields
            if not item_no_value or not description_value:
                print(f"Row {idx + 2}: Skipping - missing item_no or description")
                skipped_count += 1
                continue
            
            # Prepare product data
            product_data = {
                "user_id": row_user_id,
                "item_no": item_no_value,
                "description": description_value,
                "category": category_value if category_value else "",
                "unit": unit_value if unit_value else "Piece",
                "quantity": int(float(quantity_value or 0)),
                "unit_price": float(unit_price_value or 0),
                "discount": float(discount_value or 0),
                "vat_percent": float(vat_percent_value or 15)
            }
            
            # Find existing product
            existing_product = find_product_by_item_no(item_no_value, row_user_id)
            
            # Update or insert
            if update_or_insert_product(product_data, existing_product):
                action = "Updated" if existing_product else "Inserted"
                print(f"Row {idx + 2}: {action} purchase product - Item_No: {item_no_value}, Description: {description_value[:50]}")
                success_count += 1
            else:
                print(f"Row {idx + 2}: Failed to update/insert purchase product - Item_No: {item_no_value}")
                error_count += 1
                
        except Exception as e:
            print(f"Row {idx + 2}: Error processing - {e}")
            error_count += 1
            continue
    
    print(f"\nSummary for {excel_path.name}:")
    print(f"  ✅ Success: {success_count}")
    print(f"  ❌ Errors: {error_count}")
    print(f"  ⏭️  Skipped: {skipped_count}")
    
    return (success_count, error_count, skipped_count)


def main():
    """
    Main entry point for the Excel update script.
    Scans data1 folder for Excel files and processes them.
    """
    # Determine data1 folder path
    if len(sys.argv) > 1:
        data1_folder = Path(sys.argv[1])
    else:
        # Default: look for data1 folder in parent directory
        backend_dir = Path(__file__).parent
        data1_folder = backend_dir / "data1"
    
    # If data1 folder doesn't exist, try current directory
    if not data1_folder.exists():
        data1_folder = Path("data1")
    
    if not data1_folder.exists():
        print(f"Error: data1 folder not found at {data1_folder}")
        print("Please provide the path to the data1 folder as an argument.")
        sys.exit(1)
    
    # Get user_id from command line if provided
    default_user_id = None
    if len(sys.argv) > 2:
        default_user_id = sys.argv[2]
        print(f"Using provided user_id: {default_user_id}")
    
    # Find all Excel files in data1 folder
    excel_files = list(data1_folder.glob("*.xlsx")) + list(data1_folder.glob("*.xls"))
    
    if not excel_files:
        print(f"No Excel files found in {data1_folder}")
        sys.exit(1)
    
    print(f"Found {len(excel_files)} Excel file(s) in {data1_folder}")
    
    # Process each Excel file
    total_success = 0
    total_errors = 0
    total_skipped = 0
    
    for excel_file in excel_files:
        success, errors, skipped = process_excel_file(excel_file, default_user_id)
        total_success += success
        total_errors += errors
        total_skipped += skipped
    
    # Print final summary
    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"  ✅ Total Success: {total_success}")
    print(f"  ❌ Total Errors: {total_errors}")
    print(f"  ⏭️  Total Skipped: {total_skipped}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
