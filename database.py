"""
Database configuration and initialization.
This module sets up SQLAlchemy for database operations.
"""
from flask_sqlalchemy import SQLAlchemy
import logging
from sqlalchemy.exc import OperationalError

# Create SQLAlchemy instance
# This will be initialized with the Flask app in init_db()
db = SQLAlchemy()

logger = logging.getLogger(__name__)


def init_db(app):
    """
    Initialize the database with the Flask application.
    Creates all database tables if they don't exist.
    
    Handles race conditions when multiple workers try to create tables simultaneously.
    
    Args:
        app: Flask application instance
    """
    db.init_app(app)
    with app.app_context():
        try:
            db.create_all()
            logger.info("Database initialized successfully")
        except OperationalError as e:
            # Handle "table already exists" errors gracefully
            # This can happen when multiple workers start simultaneously
            error_msg = str(e).lower()
            # Check for various "table already exists" error messages
            # SQLite: "table invoices already exists" or "(sqlite3.OperationalError) table invoices already exists"
            # PostgreSQL: "relation 'invoices' already exists"
            is_table_exists_error = (
                "already exists" in error_msg or
                ("relation" in error_msg and "already exists" in error_msg) or  # PostgreSQL
                "duplicate table" in error_msg
            )
            
            if is_table_exists_error:
                logger.info("Database tables already exist (likely from another worker) - continuing normally")
                # This is not a fatal error - tables exist, which is what we want
                # Don't raise - just continue
                return
            else:
                # Other operational errors (like connection issues) should be raised
                logger.error(f"Database operational error: {e}")
                raise
        except Exception as e:
            # Catch all other exceptions and log them
            error_msg = str(e).lower()
            # Also check for table exists errors in the outer exception handler
            # (in case OperationalError is wrapped in another exception)
            if "already exists" in error_msg or ("table" in error_msg and "exists" in error_msg):
                logger.info("Database tables already exist (detected in outer handler) - continuing normally")
                return
            logger.error(f"Error initializing database: {e}")
            # Re-raise non-operational errors as they indicate real problems
            raise


