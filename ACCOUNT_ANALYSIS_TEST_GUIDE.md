# Account Analysis API Testing Guide

## Quick Test using cURL or Postman

### 1. Create a Daily Record

**Endpoint**: `POST /api/account-analysis/daily-record`

```bash
curl -X POST http://localhost:5000/api/account-analysis/daily-record \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test-user-123",
    "date": "2026-03-17",
    "total_cash_sale": 5000.00,
    "total_bank": 3000.00,
    "total_purchase_amount": 2000.00,
    "purchase_company_name": "ABC Trading Co.",
    "notes": "First test record"
  }'
```

**Expected Response**:
```json
{
  "id": "65f1234567890abcdef12345",
  "user_id": "test-user-123",
  "date": "2026-03-17",
  "total_cash_sale": 5000.00,
  "total_bank": 3000.00,
  "total_purchase_amount": 2000.00,
  "purchase_company_name": "ABC Trading Co.",
  "notes": "First test record",
  "created_at": "2026-03-17T10:30:00.000Z",
  "updated_at": "2026-03-17T10:30:00.000Z"
}
```

---

### 2. Get All Daily Records

**Endpoint**: `GET /api/account-analysis/daily-records`

```bash
curl http://localhost:5000/api/account-analysis/daily-records?user_id=test-user-123
```

**With date filter**:
```bash
curl "http://localhost:5000/api/account-analysis/daily-records?user_id=test-user-123&start_date=2026-03-01&end_date=2026-03-31"
```

---

### 3. Get Account Summary

**Endpoint**: `GET /api/account-analysis/summary`

**Group by day**:
```bash
curl "http://localhost:5000/api/account-analysis/summary?user_id=test-user-123&group_by=day"
```

**Group by company**:
```bash
curl "http://localhost:5000/api/account-analysis/summary?user_id=test-user-123&group_by=company"
```

**Group by month**:
```bash
curl "http://localhost:5000/api/account-analysis/summary?user_id=test-user-123&group_by=month"
```

**Expected Response**:
```json
{
  "records": [
    {
      "_id": "2026-03-17",
      "total_cash_sale": 5000.00,
      "total_bank": 3000.00,
      "total_purchase_amount": 2000.00,
      "record_count": 1
    }
  ],
  "overall_totals": {
    "total_cash_sale": 5000.00,
    "total_bank": 3000.00,
    "total_purchase_amount": 2000.00,
    "net_balance": 6000.00
  },
  "group_by": "day"
}
```

---

### 4. Update a Daily Record

**Endpoint**: `PUT /api/account-analysis/daily-records/<record_id>`

```bash
curl -X PUT http://localhost:5000/api/account-analysis/daily-records/65f1234567890abcdef12345 \
  -H "Content-Type: application/json" \
  -d '{
    "total_cash_sale": 5500.00,
    "notes": "Updated notes"
  }'
```

---

### 5. Delete a Daily Record

**Endpoint**: `DELETE /api/account-analysis/daily-records/<record_id>`

```bash
curl -X DELETE http://localhost:5000/api/account-analysis/daily-records/65f1234567890abcdef12345
```

**Expected Response**:
```json
{
  "message": "Daily record deleted successfully"
}
```

---

## Testing with Postman

1. **Import the endpoints** into Postman
2. **Set Base URL**: `http://localhost:5000`
3. **Test each endpoint** as shown above
4. **Verify responses** match expected format

## Sample Test Data

Here's some sample data you can use for testing:

### Record 1
```json
{
  "user_id": "user-123",
  "date": "2026-03-17",
  "total_cash_sale": 5000.00,
  "total_bank": 3000.00,
  "total_purchase_amount": 2000.00,
  "purchase_company_name": "ABC Trading Co.",
  "notes": "Regular business day"
}
```

### Record 2
```json
{
  "user_id": "user-123",
  "date": "2026-03-16",
  "total_cash_sale": 4500.00,
  "total_bank": 2800.00,
  "total_purchase_amount": 1500.00,
  "purchase_company_name": "XYZ Suppliers",
  "notes": "Good sales day"
}
```

### Record 3
```json
{
  "user_id": "user-123",
  "date": "2026-03-15",
  "total_cash_sale": 6000.00,
  "total_bank": 3500.00,
  "total_purchase_amount": 2500.00,
  "purchase_company_name": "ABC Trading Co.",
  "notes": "Weekend rush"
}
```

## Expected Calculations

With the above 3 records:
- **Total Cash Sales**: 15,500.00 SAR
- **Total Bank**: 9,300.00 SAR
- **Total Purchases**: 6,000.00 SAR
- **Net Balance**: 18,800.00 SAR (15,500 + 9,300 - 6,000)

**Grouped by Company**:
- ABC Trading Co.: 4,500.00 SAR purchases
- XYZ Suppliers: 1,500.00 SAR purchases

## Frontend Testing

1. **Start the backend**: `python app.py`
2. **Start frontend**: `npm run dev`
3. **Navigate to**: `http://localhost:5173/dashboard/account-analysis`
4. **Add records** using the UI
5. **Test filters** and grouping options
6. **Verify charts** display correctly
7. **Test edit/delete** operations

## Success Criteria

✅ Can create daily records
✅ Can view all records in table format
✅ Summary cards show correct totals
✅ Charts display data correctly
✅ Filters work (date range, group by)
✅ Can edit existing records
✅ Can delete records
✅ Responsive design works on mobile
