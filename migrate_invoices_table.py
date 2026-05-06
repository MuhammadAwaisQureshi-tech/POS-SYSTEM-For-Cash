"""
Migration script to update the invoices table with new columns.
Run this script once to update your existing database schema.

Usage:
    python migrate_invoices_table.py
"""
import sqlite3
import os
from pathlib import Path

def migrate_invoices_table():
    """Add missing columns to the invoices table if they don't exist."""
    # Get database path
    backend_dir = Path(__file__).parent
    data_dir = backend_dir / "data"
    db_path = data_dir / "app.db"
    
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        print("The database will be created automatically when you start the Flask app.")
        return
    
    print(f"Connecting to database at {db_path}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(invoices)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        print(f"Existing columns: {existing_columns}")
        
        # Columns to add (if they don't exist)
        columns_to_add = [
            ("invoice_no", "VARCHAR(100)"),
            ("customer_phone", "VARCHAR(50)"),
            ("customer_vat_id", "VARCHAR(100)"),
            ("customer_address", "TEXT"),
            ("quotation_price", "VARCHAR(50)"),
            ("items", "TEXT"),
            ("subtotal", "FLOAT DEFAULT 0.0"),
            ("discount", "FLOAT DEFAULT 0.0"),
            ("vat_amount", "FLOAT DEFAULT 0.0"),
            ("receiver_name", "VARCHAR(255)"),
            ("cashier_name", "VARCHAR(255)"),
        ]
        
        # Add missing columns
        added_columns = []
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                try:
                    # SQLite doesn't support adding NOT NULL columns to existing tables easily
                    # So we'll add them as nullable first
                    alter_sql = f"ALTER TABLE invoices ADD COLUMN {column_name} {column_type}"
                    cursor.execute(alter_sql)
                    added_columns.append(column_name)
                    print(f"✓ Added column: {column_name}")
                except sqlite3.OperationalError as e:
                    if "duplicate column" in str(e).lower():
                        print(f"  Column {column_name} already exists, skipping")
                    else:
                        print(f"  Error adding {column_name}: {e}")
        
        # Special handling for invoice_no - generate invoice numbers for existing rows
        if "invoice_no" in added_columns:
            # For existing rows, generate invoice numbers
            cursor.execute("SELECT id FROM invoices WHERE invoice_no IS NULL OR invoice_no = ''")
            rows_without_invoice_no = cursor.fetchall()
            if rows_without_invoice_no:
                print(f"  Generating invoice numbers for {len(rows_without_invoice_no)} existing rows...")
                from datetime import datetime
                for row_id, in rows_without_invoice_no:
                    # Generate a unique invoice number
                    invoice_no = f"{datetime.now().strftime('%Y%m')}-{row_id}"
                    cursor.execute("UPDATE invoices SET invoice_no = ? WHERE id = ?", (invoice_no, row_id))
        
        # Set default values for numeric fields on existing rows
        if "subtotal" in added_columns or "discount" in added_columns or "vat_amount" in added_columns:
            cursor.execute("""
                UPDATE invoices 
                SET subtotal = COALESCE(subtotal, 0.0),
                    discount = COALESCE(discount, 0.0),
                    vat_amount = COALESCE(vat_amount, 0.0)
                WHERE subtotal IS NULL OR discount IS NULL OR vat_amount IS NULL
            """)
        
        # Set default empty JSON array for items if it was just added
        if "items" in added_columns:
            cursor.execute("UPDATE invoices SET items = '[]' WHERE items IS NULL OR items = ''")
        
        # Commit changes
        conn.commit()
        
        if added_columns:
            print(f"\n✓ Migration completed! Added {len(added_columns)} columns: {', '.join(added_columns)}")
        else:
            print("\n✓ All columns already exist. No migration needed.")
        
    except Exception as e:
        conn.rollback()
        print(f"\n✗ Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Invoice Table Migration Script")
    print("=" * 60)
    migrate_invoices_table()
    print("=" * 60)

