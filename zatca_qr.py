"""
ZATCA Phase-1 QR Code Generator for Saudi Arabia VAT Invoices.

This module implements the ZATCA Phase-1 QR code specification:
- TLV (Tag-Length-Value) encoding
- Base64 encoding
- Only 5 required fields in exact order

ZATCA Phase-1 Fields:
1. Tag 1: Seller Name (UTF-8 string)
2. Tag 2: VAT Registration Number (15 digits)
3. Tag 3: Invoice Date & Time (ISO format: YYYY-MM-DDTHH:MM:SS)
4. Tag 4: Total Invoice Amount with VAT (2 decimals)
5. Tag 5: VAT Amount (2 decimals)
"""
import base64
import re
from datetime import datetime
from typing import Tuple


def validate_vat_number(vat_number: str) -> bool:
    """
    Validate VAT registration number (must be exactly 15 digits).
    
    Args:
        vat_number: VAT registration number string
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not vat_number:
        return False
    # Remove any spaces or dashes
    cleaned = re.sub(r'[\s\-]', '', vat_number)
    # Must be exactly 15 digits
    return cleaned.isdigit() and len(cleaned) == 15


def validate_amount(amount: str) -> bool:
    """
    Validate amount format (must have 2 decimal places).
    
    Args:
        amount: Amount as string
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not amount:
        return False
    try:
        # Try to parse as float
        num = float(amount)
        # Check if it has at most 2 decimal places
        # Convert to string with 2 decimals and compare
        formatted = f"{num:.2f}"
        return str(amount) == formatted or abs(float(amount) - num) < 0.001
    except (ValueError, TypeError):
        return False


def validate_datetime(dt_string: str) -> bool:
    """
    Validate ISO datetime format (YYYY-MM-DDTHH:MM:SS).
    
    Args:
        dt_string: Datetime string
        
    Returns:
        bool: True if valid ISO format, False otherwise
    """
    if not dt_string:
        return False
    try:
        # Try to parse ISO format
        datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        # Check format matches YYYY-MM-DDTHH:MM:SS
        pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
        return bool(re.match(pattern, dt_string))
    except (ValueError, AttributeError):
        return False


def format_amount(amount: float) -> str:
    """
    Format amount to 2 decimal places string.
    
    Args:
        amount: Amount as float
        
    Returns:
        str: Formatted amount with 2 decimals
    """
    return f"{amount:.2f}"


def format_datetime(dt: datetime) -> str:
    """
    Format datetime to ISO format (YYYY-MM-DDTHH:MM:SS).
    
    Args:
        dt: Datetime object
        
    Returns:
        str: ISO formatted datetime string
    """
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def build_tlv_field(tag: int, value: str) -> bytes:
    """
    Build a TLV (Tag-Length-Value) field.
    
    Format: [Tag (1 byte)][Length (1 byte)][Value (variable)]
    
    Args:
        tag: Tag number (1-5)
        value: Value as UTF-8 string
        
    Returns:
        bytes: TLV field as binary data
    """
    # Encode value as UTF-8
    value_bytes = value.encode('utf-8')
    length = len(value_bytes)
    
    # Validate length fits in 1 byte (max 255)
    if length > 255:
        raise ValueError(f"Value length ({length}) exceeds maximum (255) for tag {tag}")
    
    # Build TLV: Tag (1 byte) + Length (1 byte) + Value (variable)
    tlv = bytes([tag]) + bytes([length]) + value_bytes
    
    return tlv


def generate_zatca_qr(
    seller_name: str,
    vat_number: str,
    invoice_datetime: str,
    total_amount: str,
    vat_amount: str
) -> str:
    """
    Generate ZATCA Phase-1 compliant QR code Base64 string.
    
    This function builds TLV binary data from the 5 required fields,
    then encodes it to Base64. The Base64 string is what should be
    used to generate the QR code image.
    
    Args:
        seller_name: Seller name (UTF-8, Arabic/English allowed)
        vat_number: VAT registration number (must be exactly 15 digits)
        invoice_datetime: Invoice date & time in ISO format (YYYY-MM-DDTHH:MM:SS)
        total_amount: Total invoice amount with VAT (must have 2 decimals)
        vat_amount: VAT amount (must have 2 decimals)
        
    Returns:
        str: Base64 encoded TLV data (ready for QR code generation)
        
    Raises:
        ValueError: If any validation fails
    """
    # Validate inputs
    if not seller_name or not seller_name.strip():
        raise ValueError("Seller name is required")
    
    if not validate_vat_number(vat_number):
        raise ValueError(f"VAT number must be exactly 15 digits. Got: {vat_number}")
    
    if not validate_datetime(invoice_datetime):
        raise ValueError(f"Invalid datetime format. Expected YYYY-MM-DDTHH:MM:SS. Got: {invoice_datetime}")
    
    if not validate_amount(total_amount):
        raise ValueError(f"Total amount must have 2 decimal places. Got: {total_amount}")
    
    if not validate_amount(vat_amount):
        raise ValueError(f"VAT amount must have 2 decimal places. Got: {vat_amount}")
    
    # Clean VAT number (remove spaces/dashes)
    cleaned_vat = re.sub(r'[\s\-]', '', vat_number)
    
    # Build TLV fields in exact order (Tag 1-5)
    tlv_data = b''
    
    # Tag 1: Seller Name
    tlv_data += build_tlv_field(1, seller_name.strip())
    
    # Tag 2: VAT Registration Number
    tlv_data += build_tlv_field(2, cleaned_vat)
    
    # Tag 3: Invoice Date & Time
    tlv_data += build_tlv_field(3, invoice_datetime)
    
    # Tag 4: Total Invoice Amount (with VAT)
    tlv_data += build_tlv_field(4, total_amount)
    
    # Tag 5: VAT Amount
    tlv_data += build_tlv_field(5, vat_amount)
    
    # Encode to Base64
    base64_string = base64.b64encode(tlv_data).decode('utf-8')
    
    return base64_string


def decode_zatca_qr(base64_string: str) -> dict:
    """
    Decode ZATCA QR code Base64 string back to TLV fields.
    
    This is a utility function for verification/debugging.
    
    Args:
        base64_string: Base64 encoded TLV data
        
    Returns:
        dict: Dictionary with tag numbers as keys and values as strings
        
    Raises:
        ValueError: If decoding fails
    """
    try:
        # Decode Base64
        tlv_data = base64.b64decode(base64_string)
        
        result = {}
        offset = 0
        
        # Parse TLV fields
        while offset < len(tlv_data):
            if offset + 2 > len(tlv_data):
                raise ValueError("Invalid TLV data: incomplete field")
            
            # Read Tag (1 byte)
            tag = tlv_data[offset]
            offset += 1
            
            # Read Length (1 byte)
            length = tlv_data[offset]
            offset += 1
            
            # Read Value
            if offset + length > len(tlv_data):
                raise ValueError(f"Invalid TLV data: incomplete value for tag {tag}")
            
            value_bytes = tlv_data[offset:offset + length]
            value = value_bytes.decode('utf-8')
            
            result[tag] = value
            offset += length
        
        return result
    except Exception as e:
        raise ValueError(f"Failed to decode QR code: {str(e)}")


def verify_zatca_qr(
    base64_string: str,
    expected_seller_name: str,
    expected_vat_number: str,
    expected_datetime: str,
    expected_total_amount: str,
    expected_vat_amount: str
) -> Tuple[bool, list]:
    """
    Verify ZATCA QR code matches expected values.
    
    Args:
        base64_string: Base64 encoded QR code
        expected_seller_name: Expected seller name
        expected_vat_number: Expected VAT number
        expected_datetime: Expected datetime
        expected_total_amount: Expected total amount
        expected_vat_amount: Expected VAT amount
        
    Returns:
        tuple: (is_valid: bool, errors: list)
    """
    errors = []
    
    try:
        decoded = decode_zatca_qr(base64_string)
        
        # Verify Tag 1: Seller Name
        if decoded.get(1) != expected_seller_name.strip():
            errors.append(f"Tag 1 (Seller Name) mismatch: expected '{expected_seller_name}', got '{decoded.get(1)}'")
        
        # Verify Tag 2: VAT Number
        cleaned_expected_vat = re.sub(r'[\s\-]', '', expected_vat_number)
        if decoded.get(2) != cleaned_expected_vat:
            errors.append(f"Tag 2 (VAT Number) mismatch: expected '{cleaned_expected_vat}', got '{decoded.get(2)}'")
        
        # Verify Tag 3: DateTime
        if decoded.get(3) != expected_datetime:
            errors.append(f"Tag 3 (DateTime) mismatch: expected '{expected_datetime}', got '{decoded.get(3)}'")
        
        # Verify Tag 4: Total Amount
        if decoded.get(4) != expected_total_amount:
            errors.append(f"Tag 4 (Total Amount) mismatch: expected '{expected_total_amount}', got '{decoded.get(4)}'")
        
        # Verify Tag 5: VAT Amount
        if decoded.get(5) != expected_vat_amount:
            errors.append(f"Tag 5 (VAT Amount) mismatch: expected '{expected_vat_amount}', got '{decoded.get(5)}'")
        
        # Check for extra tags
        for tag in decoded.keys():
            if tag not in [1, 2, 3, 4, 5]:
                errors.append(f"Unexpected tag {tag} found in QR code")
        
        return len(errors) == 0, errors
        
    except Exception as e:
        errors.append(f"Decoding error: {str(e)}")
        return False, errors

