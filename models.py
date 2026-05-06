"""
Database models for the invoice application.
This module defines SQLAlchemy models for local database tables.
"""
from datetime import datetime
from database import db
import json


class Invoice(db.Model):
    """
    Invoice model for storing invoice data in local SQLite database.
    
    Attributes:
        id: Primary key (auto-incrementing integer)
        invoice_no: Invoice number (required)
        customer_name: Name of the customer (required)
        customer_phone: Customer phone number
        customer_vat_id: Customer VAT ID
        customer_address: Customer address
        quotation_price: Quotation price type
        items: Invoice items as JSON (required)
        subtotal: Subtotal amount (required)
        discount: Discount amount
        vat_amount: VAT amount (required)
        total_amount: Total invoice amount (required)
        currency: Currency code (defaults to "USD")
        notes: Additional notes or comments (optional)
        receiver_name: Receiver name
        cashier_name: Cashier name
        created_at: Timestamp when invoice was created (auto-generated)
    """
    __tablename__ = "invoices"

    id = db.Column(db.Integer, primary_key=True)
    invoice_no = db.Column(db.String(100), nullable=True, unique=True)  # Made nullable for migration compatibility
    customer_name = db.Column(db.String(255), nullable=False)
    customer_phone = db.Column(db.String(50), nullable=True)
    customer_vat_id = db.Column(db.String(100), nullable=True)
    customer_address = db.Column(db.Text, nullable=True)
    quotation_price = db.Column(db.String(50), nullable=True)
    items = db.Column(db.Text, nullable=True)  # JSON string - made nullable for migration compatibility
    subtotal = db.Column(db.Float, nullable=False, default=0.0)
    discount = db.Column(db.Float, nullable=False, default=0.0)
    vat_amount = db.Column(db.Float, nullable=False, default=0.0)
    total_amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), nullable=False, default="USD")
    notes = db.Column(db.Text, nullable=True)
    receiver_name = db.Column(db.String(255), nullable=True)
    cashier_name = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        """
        Convert invoice object to dictionary for JSON serialization.
        
        Returns:
            dict: Dictionary representation of the invoice
        """
        try:
            items_data = json.loads(self.items) if self.items else []
        except (json.JSONDecodeError, TypeError):
            items_data = []
        
        return {
            "id": str(self.id),
            "invoice_no": self.invoice_no,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone or "",
            "customer_vat_id": self.customer_vat_id or "",
            "customer_address": self.customer_address or "",
            "quotation_price": self.quotation_price or "",
            "items": items_data,
            "subtotal": float(self.subtotal),
            "discount": float(self.discount),
            "vat_amount": float(self.vat_amount),
            "total": float(self.total_amount),
            "currency": self.currency,
            "notes": self.notes or "",
            "receiver_name": self.receiver_name or "",
            "cashier_name": self.cashier_name or "",
            "created_at": self.created_at.isoformat() + "Z",
        }


