"""
Extra Expense routes for managing miscellaneous expense items.
All extra expense operations interact with MongoDB database.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Optional

from bson import ObjectId
from flask import Blueprint, jsonify, request

from mongodb_client import get_collection


extra_expense_bp = Blueprint("extra_expense", __name__)


def _finite_number(raw: Any, label: str) -> float:
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


def _oid_to_str(obj: Any) -> Any:
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, dict):
        out = {k: _oid_to_str(v) for k, v in obj.items()}
        if "_id" in out and "id" not in out:
            out["id"] = str(out["_id"])
        return out
    if isinstance(obj, list):
        return [_oid_to_str(x) for x in obj]
    return obj


def _normalize_item(row: Any, i: int) -> dict:
    if not isinstance(row, dict):
        raise ValueError(f"Each item must be an object (row {i + 1})")
    name = (row.get("name") or row.get("field_name") or "").strip()
    if not name:
        raise ValueError(f"Field name is required (row {i + 1})")
    value = _finite_number(row.get("value"), f"value (row {i + 1})")
    return {"name": name, "value": value}

def _parse_iso_date_yyyy_mm_dd(raw: Any, label: str) -> str:
    if raw is None:
        raise ValueError(f"{label} is required")
    s = str(raw).strip()
    if not s:
        raise ValueError(f"{label} is required")
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        raise ValueError(f"Invalid {label}. Use YYYY-MM-DD")
    return d.strftime("%Y-%m-%d")


@extra_expense_bp.get("/api/extra-expenses")
def list_extra_expenses():
    """
    List extra expenses.

    Query params:
      - user_id (optional): filter by user id
      - start_date (optional): YYYY-MM-DD
      - end_date (optional): YYYY-MM-DD
    """
    try:
        collection = get_collection("extra_expenses")
        q: dict[str, Any] = {}
        user_id = request.args.get("user_id")
        if user_id:
            q["user_id"] = user_id

        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        if start_date or end_date:
            q["date"] = {}
            if start_date:
                q["date"]["$gte"] = _parse_iso_date_yyyy_mm_dd(start_date, "start_date")
            if end_date:
                q["date"]["$lte"] = _parse_iso_date_yyyy_mm_dd(end_date, "end_date")

        docs = list(collection.find(q).sort("created_at", -1))
        return jsonify([_oid_to_str(d) for d in docs]), 200
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to fetch extra expenses: {str(e)}"}), 500


@extra_expense_bp.post("/api/extra-expenses/bulk")
def create_extra_expenses_bulk():
    """
    Create multiple extra expense items in one request.

    Body JSON:
      - user_id (required)
      - date (required): YYYY-MM-DD
      - items: [{ name, value }]
    """
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    user_id = payload.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    try:
        date_str = _parse_iso_date_yyyy_mm_dd(payload.get("date"), "date")
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    items = payload.get("items")
    if not isinstance(items, list) or len(items) == 0:
        return jsonify({"error": "items must be a non-empty array"}), 400

    try:
        normalized = [_normalize_item(row, i) for i, row in enumerate(items)]
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400

    now = datetime.utcnow().isoformat()
    docs = [
        {
            "user_id": user_id,
            "date": date_str,
            "name": r["name"],
            "value": r["value"],
            "created_at": now,
            "updated_at": now,
        }
        for r in normalized
    ]

    try:
        collection = get_collection("extra_expenses")
        res = collection.insert_many(docs)
        inserted_ids = list(res.inserted_ids or [])
        created = list(collection.find({"_id": {"$in": inserted_ids}}))
        # Keep same order as inserted_ids
        id_to_doc = {d["_id"]: d for d in created}
        ordered = [id_to_doc.get(_id) for _id in inserted_ids]
        ordered = [d for d in ordered if d is not None]
        return jsonify([_oid_to_str(d) for d in ordered]), 201
    except Exception as e:
        return jsonify({"error": f"Failed to create extra expenses: {str(e)}"}), 500


@extra_expense_bp.delete("/api/extra-expenses/<expense_id>")
def delete_extra_expense(expense_id: str):
    """Delete an extra expense item by id."""
    try:
        try:
            obj_id = ObjectId(expense_id)
        except Exception:
            return jsonify({"error": "Invalid expense ID format"}), 400

        collection = get_collection("extra_expenses")
        res = collection.delete_one({"_id": obj_id})
        if res.deleted_count == 0:
            return jsonify({"error": "Extra expense not found"}), 404
        return jsonify({"message": "Extra expense deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": f"Failed to delete extra expense: {str(e)}"}), 500


@extra_expense_bp.put("/api/extra-expenses/<expense_id>")
def update_extra_expense(expense_id: str):
    """Update one extra expense item (name/value)."""
    try:
        try:
            obj_id = ObjectId(expense_id)
        except Exception:
            return jsonify({"error": "Invalid expense ID format"}), 400

        payload = request.get_json(force=True) or {}
        patch: dict[str, Any] = {}
        if "date" in payload:
            try:
                patch["date"] = _parse_iso_date_yyyy_mm_dd(payload.get("date"), "date")
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400
        if "name" in payload or "field_name" in payload:
            name = (payload.get("name") or payload.get("field_name") or "").strip()
            if not name:
                return jsonify({"error": "name is required"}), 400
            patch["name"] = name
        if "value" in payload:
            try:
                patch["value"] = _finite_number(payload.get("value"), "value")
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400

        if not patch:
            return jsonify({"error": "No valid fields to update"}), 400

        patch["updated_at"] = datetime.utcnow().isoformat()
        collection = get_collection("extra_expenses")
        res = collection.update_one({"_id": obj_id}, {"$set": patch})
        if res.matched_count == 0:
            return jsonify({"error": "Extra expense not found"}), 404

        doc = collection.find_one({"_id": obj_id})
        return jsonify(_oid_to_str(doc)), 200
    except Exception as e:
        return jsonify({"error": f"Failed to update extra expense: {str(e)}"}), 500

