"""
Main Flask application factory.
This module creates and configures the Flask app, registers blueprints,
and sets up database connections.
"""
from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import atexit
from dotenv import load_dotenv
from database import init_db
from routes import products, invoices, debug, auth, purchase_products, company_settings, customers
from mongodb_client import close_mongodb_client

# Load environment variables at module level (before app creation)
# Try loading from project root first, then backend directory
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
if os.path.exists(env_path):
    load_dotenv(env_path)

backend_env = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(backend_env):
    load_dotenv(backend_env, override=True)

# Also try loading from current directory (if running from backend/)
load_dotenv(override=False)


def create_app():
    """
    Application factory function.
    Creates and configures the Flask application instance.
    
    Returns:
        Flask: Configured Flask application instance
    """
    app = Flask(__name__)

    # Database configuration
    # Use DATABASE_URL if provided (for production/Supabase), else use local SQLite
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        # Local SQLite database stored in data folder
        # Ensure data directory exists
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        
        db_path = os.path.abspath(
            os.path.join(data_dir, "app.db")
        )
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Enable CORS for all API routes with explicit configuration
    # This supports cross-origin requests from frontend to backend
    # Allow common development ports and production URLs
    allowed_origins = [
        "https://gleaming-hummingbird-6934de.netlify.app",
        "http://localhost:5173",
        "http://localhost:5000",
        "http://localhost:8080",
        "http://localhost:8081",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:8081",
        "http://127.0.0.1:5173",
        "https://zahid-cms.vercel.app",
        "https://zahid-cms-cash.vercel.app",
    ]
    
    # Simplified and more reliable CORS configuration
    # Enable CORS for all routes with explicit origin matching
    CORS(app, 
         origins=allowed_origins,
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
         allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
         expose_headers=["Content-Type", "Authorization"],
         supports_credentials=True,
         max_age=3600
    )

    # Handle OPTIONS preflight requests explicitly for all API routes
    @app.before_request
    def handle_preflight():
        if request.method == "OPTIONS":
            origin = request.headers.get('Origin')
            # Normalize origin (remove trailing slash)
            normalized_origin = origin.rstrip('/') if origin else None
            # Check if origin matches (with or without trailing slash)
            origin_matches = (
                origin in allowed_origins or 
                normalized_origin in allowed_origins or
                any(allowed.rstrip('/') == normalized_origin for allowed in allowed_origins)
            )
            if origin and origin_matches:
                response = jsonify({})
                # Use the original origin from request
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
                response.headers['Access-Control-Allow-Credentials'] = 'true'
                response.headers['Access-Control-Max-Age'] = '3600'
                return response
            # If origin doesn't match, still return 200 but without CORS headers
            # This prevents CORS errors from breaking the request
            return jsonify({}), 200

    # Initialize database
    init_db(app)

    # Register blueprints (route modules)
    app.register_blueprint(products.products_bp)
    app.register_blueprint(invoices.invoices_bp)
    app.register_blueprint(debug.debug_bp)
    app.register_blueprint(auth.auth_bp)
    app.register_blueprint(purchase_products.purchase_products_bp)
    app.register_blueprint(company_settings.company_settings_bp)
    app.register_blueprint(customers.customers_bp)
    
    # Register shutdown handler to close MongoDB connection
    @app.teardown_appcontext
    def close_db(error):
        """Close MongoDB connection on app context teardown."""
        # Don't close here as we want to reuse the connection
        # Connection will be closed on app shutdown via atexit
        pass
    
    # Register cleanup function to run on exit
    atexit.register(close_mongodb_client)

    # Additional CORS headers as fallback (ensures headers are always set)
    @app.after_request
    def after_request(response):
        origin = request.headers.get('Origin')
        if origin:
            # Normalize origin for comparison
            normalized_origin = origin.rstrip('/')
            # Check if origin matches (with or without trailing slash)
            origin_matches = (
                origin in allowed_origins or 
                normalized_origin in allowed_origins or
                any(allowed.rstrip('/') == normalized_origin for allowed in allowed_origins)
            )
            if origin_matches:
                # Always set CORS headers for allowed origins
                response.headers['Access-Control-Allow-Origin'] = origin
                response.headers['Access-Control-Allow-Credentials'] = 'true'
                response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Accept'
                response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS, PATCH'
                response.headers['Access-Control-Max-Age'] = '3600'
        return response

    return app


# Create app instance for gunicorn (app:app)
app = create_app()


if __name__ == "__main__":
    """
    Run the Flask development server.
    This is only used for local development.
    For production, use a WSGI server like Gunicorn.
    """
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)


