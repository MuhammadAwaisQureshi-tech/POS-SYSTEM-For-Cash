"""
Simple authentication routes for user registration and login.
Uses a simple users collection in MongoDB with username, email, and password.
"""
from flask import Blueprint, request, jsonify
from mongodb_client import get_collection
import hashlib
import secrets
import uuid
from datetime import datetime
from bson import ObjectId
from typing import Any

# Create a Blueprint for auth routes
auth_bp = Blueprint('auth', __name__)


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


def hash_password(password: str) -> str:
    """
    Hash a password using SHA-256 (simple hashing for basic auth).
    In production, consider using bcrypt or argon2.
    """
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    """
    Verify a password against a hash.
    """
    return hash_password(password) == hashed


@auth_bp.post("/api/auth/register")
def register():
    """
    Register a new user.
    Expects JSON: { "username": "...", "email": "...", "password": "..." }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        username = data.get("username", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "").strip()
        
        # Validation
        if not username:
            return jsonify({"error": "Username is required"}), 400
        if not email:
            return jsonify({"error": "Email is required"}), 400
        if not password or len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        # Check if email already exists
        collection = get_collection("users")
        existing_user = collection.find_one({"email": email})
        
        if existing_user:
            return jsonify({"error": "Email already registered"}), 400
        
        # Check if username already exists
        existing_username = collection.find_one({"username": username})
        
        if existing_username:
            return jsonify({"error": "Username already taken"}), 400
        
        # Hash password
        hashed_password = hash_password(password)
        
        # Create user
        user_data = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password": hashed_password,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        result = collection.insert_one(user_data)
        
        if result.inserted_id:
            # Return user data (without password)
            user_data.pop("password", None)
            user_data = convert_objectid_to_str(user_data)
            return jsonify({
                "message": "User registered successfully",
                "user": {
                    "id": user_data["id"],
                    "username": user_data["username"],
                    "email": user_data["email"]
                }
            }), 201
        else:
            return jsonify({"error": "Failed to create user"}), 500
            
    except RuntimeError as e:
        # Handle MongoDB connection errors specifically
        error_msg = str(e)
        if "shutdown" in error_msg.lower() or "thread" in error_msg.lower():
            return jsonify({
                "error": "Database connection error. Please try again in a moment.",
                "details": "The server may be restarting. Please wait a few seconds and try again."
            }), 503
        return jsonify({"error": f"Registration failed: {error_msg}"}), 500
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Registration failed: {error_msg}"}), 500


@auth_bp.post("/api/auth/login")
def login():
    """
    Login a user.
    Expects JSON: { "email": "...", "password": "..." }
    Returns: { "user": {...}, "token": "..." }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        email = data.get("email", "").strip().lower()
        password = data.get("password", "").strip()
        
        # Validation
        if not email:
            return jsonify({"error": "Email is required"}), 400
        if not password:
            return jsonify({"error": "Password is required"}), 400
        
        # Find user by email
        collection = get_collection("users")
        user = collection.find_one({"email": email})
        
        if not user:
            return jsonify({"error": "Invalid email or password"}), 401
        
        # Verify password
        if not verify_password(password, user.get("password", "")):
            return jsonify({"error": "Invalid email or password"}), 401
        
        # Generate a simple token (in production, use JWT)
        token = secrets.token_urlsafe(32)
        
        # Return user data (without password) and token
        return jsonify({
            "message": "Login successful",
            "user": {
                "id": user.get("id", str(user.get("_id", ""))),
                "username": user.get("username", ""),
                "email": user.get("email", "")
            },
            "token": token
        }), 200
            
    except RuntimeError as e:
        # Handle MongoDB connection errors specifically
        error_msg = str(e)
        if "shutdown" in error_msg.lower() or "thread" in error_msg.lower():
            return jsonify({
                "error": "Database connection error. Please try again in a moment.",
                "details": "The server may be restarting. Please wait a few seconds and try again."
            }), 503
        return jsonify({"error": f"Login failed: {error_msg}"}), 500
    except Exception as e:
        error_msg = str(e)
        return jsonify({"error": f"Login failed: {error_msg}"}), 500
