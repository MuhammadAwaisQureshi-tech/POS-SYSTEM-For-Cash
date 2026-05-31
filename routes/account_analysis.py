"""
Account Analysis routes for managing daily account records.
All account analysis operations interact with MongoDB database.
"""
import json
import math
import os
from flask import Blueprint, request, jsonify, Response
from werkzeug.utils import secure_filename
from mongodb_client import get_collection
from bson import ObjectId
from datetime import datetime
from typing import Any, Optional, Tuple

from services.google_drive import (
    build_drive_invoice_name,
    download_drive_file,
    upload_invoice_bytes,
)

# Legacy rows: BSON Binary in MongoDB (16MB doc limit). New uploads go to Google Drive.
MAX_PURCHASE_INVOICE_BYTES = 10 * 1024 * 1024
ALLOWED_INVOICE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

# Create a Blueprint for account analysis routes
account_analysis_bp = Blueprint('account_analysis', __name__)


def _parse_finite_amount(raw: Any, label: str) -> float:
    """Parse a required numeric field; reject NaN, infinity, and non-numeric values."""
    if raw is None:
        raise ValueError(f"{label} is required")
    if isinstance(raw, str) and not raw.strip():
        raise ValueError(f"{label} is required")
    try:
        x = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a valid number")
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"{label} must be a finite number")
    return x


def _sanitize_daily_record_amount_fields(d: dict) -> None:
    """Ensure JSON responses never contain NaN/inf (invalid in standard JSON)."""
    for key in ("total_cash_sale", "total_bank", "total_purchase_amount", "total_expenses"):
        if key not in d:
            if key == "total_expenses":
                d[key] = 0.0
            continue
        v = d.get(key)
        try:
            x = float(v)
            d[key] = x if math.isfinite(x) else 0.0
        except (TypeError, ValueError):
            d[key] = 0.0


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


def _company_invoice_has_attachment(c: dict) -> bool:
    return bool(c.get("purchase_invoice_url") or c.get("purchase_invoice_data"))


def _company_invoice_storage(c: dict) -> Optional[str]:
    if c.get("purchase_invoice_url"):
        return "drive"
    if c.get("purchase_invoice_data"):
        return "mongodb"
    return None


def _serialize_company_invoice_json(c: dict) -> dict:
    return {
        "purchase_company_name": c.get("purchase_company_name"),
        "company_phone": (c.get("company_phone") or "").strip(),
        "has_purchase_invoice": _company_invoice_has_attachment(c),
        "purchase_invoice_storage": _company_invoice_storage(c),
        "purchase_invoice_url": c.get("purchase_invoice_url") or None,
        "purchase_invoice_filename": c.get("purchase_invoice_filename"),
        "purchase_invoice_content_type": c.get("purchase_invoice_content_type"),
    }


def _get_invoice_info_at_index(record: dict, company_index: int) -> dict:
    """Invoice attachment fields for one supplier row (Drive URL or legacy Mongo binary)."""
    empty: dict = {
        "raw": None,
        "filename": None,
        "content_type": None,
        "url": None,
        "drive_file_id": None,
    }
    companies = record.get("purchase_companies")
    if companies and isinstance(companies, list) and 0 <= company_index < len(companies):
        c = companies[company_index]
        if not isinstance(c, dict):
            return empty
        return {
            "raw": c.get("purchase_invoice_data"),
            "filename": c.get("purchase_invoice_filename"),
            "content_type": c.get("purchase_invoice_content_type"),
            "url": c.get("purchase_invoice_url"),
            "drive_file_id": c.get("purchase_invoice_drive_file_id"),
        }
    if company_index == 0:
        return {
            "raw": record.get("purchase_invoice_data"),
            "filename": record.get("purchase_invoice_filename"),
            "content_type": record.get("purchase_invoice_content_type"),
            "url": record.get("purchase_invoice_url"),
            "drive_file_id": record.get("purchase_invoice_drive_file_id"),
        }
    return empty


def daily_record_to_json(doc: Optional[dict]) -> Optional[dict]:
    """Serialize a daily record for JSON responses (never embed binary file data)."""
    if doc is None:
        return None
    d = dict(doc)
    _sanitize_daily_record_amount_fields(d)
    companies_raw = d.get("purchase_companies")
    companies_out: list[dict] = []

    if isinstance(companies_raw, list) and len(companies_raw) == 0:
        d.pop("purchase_invoice_data", None)
        d.pop("purchase_invoice_drive_file_id", None)
    elif companies_raw and isinstance(companies_raw, list) and len(companies_raw) > 0:
        for c in companies_raw:
            if not isinstance(c, dict):
                continue
            companies_out.append(_serialize_company_invoice_json(c))
        d.pop("purchase_invoice_data", None)
        d.pop("purchase_invoice_drive_file_id", None)
    else:
        legacy_row = {
            "purchase_company_name": d.get("purchase_company_name"),
            "company_phone": (d.get("company_phone") or "").strip(),
            "purchase_invoice_url": d.get("purchase_invoice_url"),
            "purchase_invoice_data": d.get("purchase_invoice_data"),
            "purchase_invoice_filename": d.get("purchase_invoice_filename"),
            "purchase_invoice_content_type": d.get("purchase_invoice_content_type"),
        }
        companies_out.append(_serialize_company_invoice_json(legacy_row))
        d.pop("purchase_invoice_data", None)
        d.pop("purchase_invoice_drive_file_id", None)

    d["purchase_companies"] = companies_out
    if companies_out:
        first = companies_out[0]
        d["purchase_company_name"] = first.get("purchase_company_name")
        d["company_phone"] = first.get("company_phone")
        d["has_purchase_invoice"] = first.get("has_purchase_invoice", False)
        d["purchase_invoice_storage"] = first.get("purchase_invoice_storage")
        d["purchase_invoice_url"] = first.get("purchase_invoice_url")
        d["purchase_invoice_filename"] = first.get("purchase_invoice_filename")
        d["purchase_invoice_content_type"] = first.get("purchase_invoice_content_type")
    else:
        d["has_purchase_invoice"] = False
        d["purchase_invoice_storage"] = None
        d["purchase_invoice_url"] = None

    d = convert_objectid_to_str(d)
    return d


def _parse_purchase_companies_meta(payload: dict) -> list[dict]:
    """
    Build a list of {purchase_company_name, company_phone} from JSON field or legacy flat fields.
    """
    pc_raw = payload.get("purchase_companies")
    if pc_raw is not None:
        if isinstance(pc_raw, str):
            try:
                arr = json.loads(pc_raw)
            except (json.JSONDecodeError, TypeError):
                raise ValueError("Invalid purchase_companies JSON")
        elif isinstance(pc_raw, list):
            arr = pc_raw
        else:
            raise ValueError("purchase_companies must be a JSON array")
        if not isinstance(arr, list):
            raise ValueError("purchase_companies must be a JSON array")
        if len(arr) == 0:
            return []
        out: list[dict] = []
        for i, row in enumerate(arr):
            if not isinstance(row, dict):
                raise ValueError("Each purchase company must be an object")
            name = (row.get("purchase_company_name") or "").strip()
            if not name:
                raise ValueError(f"Purchase company name is required (row {i + 1})")
            phone = (row.get("company_phone") or "").strip()
            out.append({"purchase_company_name": name, "company_phone": phone})
        return out

    purchase_company_name = (payload.get("purchase_company_name") or "").strip()
    if not purchase_company_name:
        raise ValueError("purchase_company_name is required")
    company_phone = (payload.get("company_phone") or "").strip()
    return [{"purchase_company_name": purchase_company_name, "company_phone": company_phone}]


def _parse_invoice_upload(
    file_storage,
    *,
    record_date: str,
    company_index: int = 0,
) -> Optional[dict]:
    """Validate file, upload to Google Drive, return MongoDB fields (no binary)."""
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
    mime = file_storage.content_type or "application/octet-stream"
    drive_name = build_drive_invoice_name(record_date, company_index, safe_name)
    try:
        uploaded = upload_invoice_bytes(
            data, safe_name, mime, drive_display_name=drive_name
        )
    except RuntimeError as exc:
        raise ValueError(f"Google Drive upload failed: {exc}") from exc
    return {
        "purchase_invoice_filename": safe_name,
        "purchase_invoice_content_type": mime,
        "purchase_invoice_url": uploaded.get("webViewLink"),
        "purchase_invoice_drive_file_id": uploaded.get("file_id"),
    }


def _apply_purchase_invoice_set_fields(
    record: dict, inv: dict, company_index: int
) -> Tuple[dict, dict]:
    """Build MongoDB $set / $unset for a Drive-stored purchase invoice."""
    inv_ts = datetime.utcnow().isoformat()
    drive_fields = {
        "purchase_invoice_filename": inv["purchase_invoice_filename"],
        "purchase_invoice_content_type": inv["purchase_invoice_content_type"],
        "purchase_invoice_url": inv.get("purchase_invoice_url"),
        "purchase_invoice_drive_file_id": inv.get("purchase_invoice_drive_file_id"),
    }
    companies = record.get("purchase_companies")
    if companies and isinstance(companies, list) and len(companies) > company_index:
        prefix = f"purchase_companies.{company_index}"
        set_fields = {f"{prefix}.{k}": v for k, v in drive_fields.items()}
        set_fields["updated_at"] = inv_ts
        unset_fields = {f"{prefix}.purchase_invoice_data": ""}
        return set_fields, unset_fields
    if isinstance(companies, list) and len(companies) == 0 and company_index == 0:
        row = {
            "purchase_company_name": (record.get("purchase_company_name") or "").strip(),
            "company_phone": (record.get("company_phone") or "").strip(),
            **drive_fields,
            "purchase_invoice_data": None,
        }
        return {"purchase_companies": [row], "updated_at": inv_ts}, {
            "purchase_invoice_data": ""
        }
    set_fields = {**drive_fields, "updated_at": inv_ts}
    return set_fields, {"purchase_invoice_data": ""}


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
    
    Optional fields:
        - total_expenses: Other daily expenses (SAR); defaults to 0 if omitted
        - purchase_companies: JSON array of suppliers (may be empty [])
        - purchase_company_name / company_phone: legacy single-row fields
        - notes: Additional notes or comments
    
    Returns:
        Created daily record object with 201 status code
    
    Accepts application/json or multipart/form-data.
    For multiple suppliers, send purchase_companies as a JSON array string and optional files
    purchase_invoice_0, purchase_invoice_1, ... (PDF/image, max 10MB each).
    Legacy single-row multipart may use purchase_invoice for the first row only.
    """
    payload = {}
    invoice_file = None
    # Use mimetype (normalized lowercase); substring match on content_type fails for
    # "Multipart/form-data" from some clients/browsers.
    files = None
    if request.mimetype == "multipart/form-data":
        payload = {k: request.form.get(k) for k in request.form}
        invoice_file = request.files.get("purchase_invoice")
        files = request.files
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
    total_expenses_raw = payload.get("total_expenses")
    notes = payload.get("notes") or ""

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

    try:
        companies_meta = _parse_purchase_companies_meta(payload)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    if companies_meta:
        purchase_company_name = companies_meta[0]["purchase_company_name"]
        company_phone = companies_meta[0]["company_phone"]
    else:
        purchase_company_name = ""
        company_phone = ""

    # Validate and convert amounts (reject NaN / inf — they break JSON responses)
    try:
        total_cash_sale = _parse_finite_amount(total_cash_sale, "total_cash_sale")
        total_bank = _parse_finite_amount(total_bank, "total_bank")
        total_purchase_amount = _parse_finite_amount(
            total_purchase_amount, "total_purchase_amount"
        )
        if total_expenses_raw is None or (
            isinstance(total_expenses_raw, str) and not str(total_expenses_raw).strip()
        ):
            total_expenses = 0.0
        else:
            total_expenses = _parse_finite_amount(total_expenses_raw, "total_expenses")
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    # Parse date
    try:
        record_date = datetime.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    # Prepare daily record document
    now = datetime.utcnow()
    record_date_str = record_date.strftime("%Y-%m-%d")
    purchase_companies_rows: list[dict] = []
    try:
        for i, comp in enumerate(companies_meta):
            row = {
                "purchase_company_name": comp["purchase_company_name"],
                "company_phone": comp["company_phone"],
                "purchase_invoice_filename": None,
                "purchase_invoice_content_type": None,
                "purchase_invoice_url": None,
                "purchase_invoice_drive_file_id": None,
                "purchase_invoice_data": None,
            }
            f = None
            if files is not None:
                f = files.get(f"purchase_invoice_{i}")
            elif i == 0 and invoice_file is not None:
                f = invoice_file
            if f is not None and f.filename and str(f.filename).strip():
                inv = _parse_invoice_upload(
                    f, record_date=record_date_str, company_index=i
                )
                if inv:
                    row.update(inv)
            purchase_companies_rows.append(row)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    daily_record_doc = {
        "user_id": user_id,
        "date": record_date.strftime("%Y-%m-%d"),
        "total_cash_sale": total_cash_sale,
        "total_bank": total_bank,
        "total_purchase_amount": total_purchase_amount,
        "total_expenses": total_expenses,
        "purchase_company_name": purchase_company_name,
        "company_phone": company_phone,
        "notes": notes,
        "purchase_companies": purchase_companies_rows,
        # Legacy top-level invoice fields (older rows only); new rows use purchase_companies[*] only.
        "purchase_invoice_filename": None,
        "purchase_invoice_content_type": None,
        "purchase_invoice_data": None,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

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
    """Download purchase invoice: Google Drive (new) or MongoDB binary (legacy)."""
    try:
        company_index = request.args.get("company_index", default=0, type=int)
        if company_index < 0:
            return jsonify({"error": "Invalid company_index"}), 400
        collection = get_collection("account_analysis_daily")
        _, record = _load_daily_record(collection, record_id)
        if not record:
            return jsonify({"error": "Daily record not found"}), 404
        info = _get_invoice_info_at_index(record, company_index)
        filename = info["filename"] or "invoice"
        ctype = info["content_type"] or "application/octet-stream"

        if info["drive_file_id"]:
            try:
                data, drive_mime = download_drive_file(info["drive_file_id"])
            except Exception as exc:
                return jsonify({"error": f"Failed to load invoice from Drive: {exc}"}), 500
            return Response(
                data,
                mimetype=drive_mime or ctype,
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Cache-Control": "private, max-age=0",
                },
            )

        raw = info["raw"]
        if not raw:
            return jsonify({"error": "No purchase invoice attached"}), 404
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
        company_index = request.form.get("company_index", default=0, type=int)
        if company_index < 0:
            return jsonify({"error": "Invalid company_index"}), 400
        record_date_for_upload = datetime.utcnow().strftime("%Y-%m-%d")
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    try:
        collection = get_collection("account_analysis_daily")
        obj_id, record = _load_daily_record(collection, record_id)
        if not record:
            return jsonify({"error": "Daily record not found"}), 404
        record_date_for_upload = (record.get("date") or record_date_for_upload)[:10]
        try:
            inv = _parse_invoice_upload(
                request.files["file"],
                record_date=record_date_for_upload,
                company_index=company_index,
            )
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        if not inv:
            return jsonify({"error": "No file selected"}), 400
        set_fields, unset_fields = _apply_purchase_invoice_set_fields(
            record, inv, company_index
        )
        collection.update_one(
            {"_id": obj_id}, {"$set": set_fields, "$unset": unset_fields}
        )
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
        - total_cash_sale, total_bank, total_purchase_amount, total_expenses
        - purchase_company_name, company_phone, notes
    
    Accepts application/json or multipart/form-data. For multipart, you may send
    ``purchase_invoice_0``, ``purchase_invoice_1``, ... to replace invoices per company row,
    or a single ``file`` / ``purchase_invoice`` with optional ``company_index`` (default 0).
    
    Returns:
        Updated daily record object
    """
    try:
        allowed = {
            "total_cash_sale", "total_bank", "total_purchase_amount", "total_expenses",
            "purchase_company_name", "company_phone", "notes"
        }
        multi_inv: dict[int, dict] = {}
        company_index = 0
        pending_invoice_files: dict[int, Any] = {}

        if request.mimetype and request.mimetype.startswith("multipart/form-data"):
            data = {k: request.form.get(k) for k in allowed if k in request.form}
            company_index = request.form.get("company_index", default=0, type=int)
            if company_index < 0:
                return jsonify({"error": "Invalid company_index"}), 400
            prefix = "purchase_invoice_"
            for key in request.files:
                if key.startswith(prefix):
                    suffix = key[len(prefix) :]
                    if suffix.isdigit():
                        pending_invoice_files[int(suffix)] = request.files[key]
            if not pending_invoice_files:
                invoice_file_storage = request.files.get("file") or request.files.get(
                    "purchase_invoice"
                )
                if invoice_file_storage is not None:
                    pending_invoice_files[company_index] = invoice_file_storage
        else:
            data = request.get_json(silent=True)
            if data is None:
                data = {}
            if not isinstance(data, dict):
                return jsonify({"error": "Invalid JSON"}), 400

        update = {k: data[k] for k in allowed if k in data}
        if "company_phone" in update and update["company_phone"] is not None:
            update["company_phone"] = str(update["company_phone"]).strip()

        if not update and not pending_invoice_files:
            return jsonify({"error": "No valid fields to update"}), 400

        # Coerce numeric fields to proper types (reject NaN / inf)
        for k in ("total_cash_sale", "total_bank", "total_purchase_amount", "total_expenses"):
            if k in update and update[k] is not None:
                try:
                    update[k] = _parse_finite_amount(update[k], k)
                except ValueError as ve:
                    return jsonify({"error": str(ve)}), 400

        collection = get_collection("account_analysis_daily")

        # Convert string ID to ObjectId
        try:
            obj_id = ObjectId(record_id)
        except:
            return jsonify({"error": "Invalid record ID format"}), 400

        existing = collection.find_one({"_id": obj_id})
        if not existing:
            return jsonify({"error": "Daily record not found"}), 404

        record_date_str = (existing.get("date") or datetime.utcnow().strftime("%Y-%m-%d"))[:10]
        for idx, file_storage in pending_invoice_files.items():
            try:
                inv = _parse_invoice_upload(
                    file_storage, record_date=record_date_str, company_index=idx
                )
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400
            if inv:
                multi_inv[idx] = inv

        pcs = existing.get("purchase_companies")
        if isinstance(pcs, list) and len(pcs) > 0:
            for idx in multi_inv:
                if idx < 0 or idx >= len(pcs):
                    return jsonify(
                        {"error": f"No supplier row at index {idx} (this record has {len(pcs)})"}
                    ), 400
        else:
            for idx in multi_inv:
                if idx != 0:
                    return jsonify(
                        {
                            "error": "This record has a single supplier slot; use invoice index 0 only"
                        }
                    ), 400

        nested_patch = {}
        invoice_merged_into_nested = False
        if pcs and isinstance(pcs, list) and len(pcs) > 0:
            if "purchase_company_name" in update:
                nested_patch["purchase_companies.0.purchase_company_name"] = update["purchase_company_name"]
            if "company_phone" in update:
                nested_patch["purchase_companies.0.company_phone"] = update["company_phone"]
        elif isinstance(pcs, list) and len(pcs) == 0 and (
            "purchase_company_name" in update
            or "company_phone" in update
            or multi_inv
        ):
            name = (existing.get("purchase_company_name") or "").strip()
            if "purchase_company_name" in update:
                name = str(update.get("purchase_company_name") or "").strip()
            phone = (existing.get("company_phone") or "").strip()
            if "company_phone" in update and update["company_phone"] is not None:
                phone = str(update["company_phone"]).strip()
            row = {
                "purchase_company_name": name,
                "company_phone": phone,
                "purchase_invoice_filename": None,
                "purchase_invoice_content_type": None,
                "purchase_invoice_url": None,
                "purchase_invoice_drive_file_id": None,
                "purchase_invoice_data": None,
            }
            if 0 in multi_inv:
                inv0 = multi_inv[0]
                row["purchase_invoice_filename"] = inv0["purchase_invoice_filename"]
                row["purchase_invoice_content_type"] = inv0["purchase_invoice_content_type"]
                row["purchase_invoice_url"] = inv0.get("purchase_invoice_url")
                row["purchase_invoice_drive_file_id"] = inv0.get(
                    "purchase_invoice_drive_file_id"
                )
                invoice_merged_into_nested = True
            nested_patch["purchase_companies"] = [row]

        all_set = {**update, **nested_patch}
        all_unset: dict = {}
        if multi_inv and not invoice_merged_into_nested:
            for idx in sorted(multi_inv.keys()):
                frag_set, frag_unset = _apply_purchase_invoice_set_fields(
                    existing, multi_inv[idx], idx
                )
                frag_set.pop("updated_at", None)
                all_set = {**all_set, **frag_set}
                all_unset = {**all_unset, **frag_unset}

        all_set["updated_at"] = datetime.utcnow().isoformat()

        update_doc: dict = {"$set": all_set}
        if all_unset:
            update_doc["$unset"] = all_unset

        result = collection.update_one({"_id": obj_id}, update_doc)
        
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
                    "total_expenses": {"$sum": {"$ifNull": ["$total_expenses", 0]}},
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
                    "total_expenses": {"$sum": {"$ifNull": ["$total_expenses", 0]}},
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
                    "total_expenses": {"$sum": {"$ifNull": ["$total_expenses", 0]}},
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
                    "total_expenses": {"$sum": {"$ifNull": ["$total_expenses", 0]}},
                    "record_count": {"$sum": 1}
                }
            })
        
        # Sort stage
        pipeline.append({"$sort": {"_id": -1}})
        
        # Execute aggregation
        result = list(collection.aggregate(pipeline))
        
        # Convert ObjectId to string
        result = convert_objectid_to_str(result)
        for r in result:
            if isinstance(r, dict):
                _sanitize_daily_record_amount_fields(r)

        # Calculate overall totals (NaN in DB would otherwise poison sums / JSON)
        overall_totals = {
            "total_cash_sale": sum(r.get("total_cash_sale", 0) for r in result),
            "total_bank": sum(r.get("total_bank", 0) for r in result),
            "total_purchase_amount": sum(r.get("total_purchase_amount", 0) for r in result),
            "total_expenses": sum(r.get("total_expenses", 0) for r in result),
            "net_balance": sum(
                r.get("total_cash_sale", 0)
                + r.get("total_bank", 0)
                - r.get("total_purchase_amount", 0)
                for r in result
            ),
        }
        
        return jsonify({
            "records": result,
            "overall_totals": overall_totals,
            "group_by": group_by
        })
        
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Failed to fetch account summary: {error_msg}"}), 500
