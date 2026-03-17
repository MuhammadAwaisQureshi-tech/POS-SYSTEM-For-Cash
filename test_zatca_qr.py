"""
ZATCA QR Code Verification Utility

This script can be used to test and verify ZATCA QR code generation.
It demonstrates how to generate QR codes and decode them for verification.

Usage:
    python -m backend.test_zatca_qr
"""
from zatca_qr import (
    generate_zatca_qr,
    decode_zatca_qr,
    verify_zatca_qr,
    format_datetime,
    format_amount
)
from datetime import datetime


def test_qr_generation():
    """Test QR code generation with sample data."""
    print("=" * 60)
    print("ZATCA QR Code Generation Test")
    print("=" * 60)
    
    # Sample invoice data
    seller_name = "Zahid POS System لقطع غيار التكييف والتبريد"
    vat_number = "314265267200003"
    invoice_datetime = format_datetime(datetime.now())
    total_amount = format_amount(1000.50)
    vat_amount = format_amount(150.08)
    
    print(f"\nInput Data:")
    print(f"  Seller Name: {seller_name}")
    print(f"  VAT Number: {vat_number}")
    print(f"  Invoice DateTime: {invoice_datetime}")
    print(f"  Total Amount: {total_amount}")
    print(f"  VAT Amount: {vat_amount}")
    
    try:
        # Generate QR code
        qr_code = generate_zatca_qr(
            seller_name=seller_name,
            vat_number=vat_number,
            invoice_datetime=invoice_datetime,
            total_amount=total_amount,
            vat_amount=vat_amount
        )
        
        print(f"\n✓ QR Code Generated Successfully")
        print(f"  Base64 String: {qr_code}")
        print(f"  Length: {len(qr_code)} characters")
        
        # Decode and verify
        print(f"\n" + "-" * 60)
        print("Decoding QR Code...")
        print("-" * 60)
        
        decoded = decode_zatca_qr(qr_code)
        
        print(f"\nDecoded Fields:")
        for tag in sorted(decoded.keys()):
            field_names = {
                1: "Seller Name",
                2: "VAT Registration Number",
                3: "Invoice Date & Time",
                4: "Total Invoice Amount",
                5: "VAT Amount"
            }
            print(f"  Tag {tag} ({field_names.get(tag, 'Unknown')}): {decoded[tag]}")
        
        # Verify
        print(f"\n" + "-" * 60)
        print("Verifying QR Code...")
        print("-" * 60)
        
        is_valid, errors = verify_zatca_qr(
            qr_code,
            seller_name,
            vat_number,
            invoice_datetime,
            total_amount,
            vat_amount
        )
        
        if is_valid:
            print(f"\n✓ QR Code Verification: PASSED")
        else:
            print(f"\n✗ QR Code Verification: FAILED")
            for error in errors:
                print(f"  - {error}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def test_validation():
    """Test validation functions."""
    print("\n" + "=" * 60)
    print("Validation Tests")
    print("=" * 60)
    
    from zatca_qr import validate_vat_number, validate_amount, validate_datetime
    
    # Test VAT number validation
    print("\nVAT Number Validation:")
    test_cases = [
        ("314265267200003", True),
        ("31426526720000", False),  # Too short
        ("3142652672000034", False),  # Too long
        ("314-265-267-200-003", True),  # With dashes (should be cleaned)
        ("314 265 267 200 003", True),  # With spaces (should be cleaned)
    ]
    
    for vat, expected in test_cases:
        result = validate_vat_number(vat)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{vat}' -> {result} (expected {expected})")
    
    # Test amount validation
    print("\nAmount Validation:")
    test_cases = [
        ("1000.50", True),
        ("1000.5", False),  # Missing second decimal
        ("1000.501", False),  # Too many decimals
        ("1000.00", True),
        ("0.01", True),
    ]
    
    for amount, expected in test_cases:
        result = validate_amount(amount)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{amount}' -> {result} (expected {expected})")
    
    # Test datetime validation
    print("\nDateTime Validation:")
    test_cases = [
        ("2024-01-15T10:30:45", True),
        ("2024-01-15T10:30:45Z", False),  # Has Z suffix
        ("2024-01-15", False),  # Missing time
        ("2024-01-15T10:30", False),  # Missing seconds
        ("24-01-15T10:30:45", False),  # Wrong year format
    ]
    
    for dt, expected in test_cases:
        result = validate_datetime(dt)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{dt}' -> {result} (expected {expected})")


if __name__ == "__main__":
    print("\n")
    success = test_qr_generation()
    test_validation()
    
    print("\n" + "=" * 60)
    if success:
        print("All tests completed!")
    else:
        print("Some tests failed. Please check the output above.")
    print("=" * 60 + "\n")

