"""
MongoDB client configuration and initialization.
This module handles connection to MongoDB database.
"""
import os
import sys
import threading
from urllib.parse import quote_plus, urlparse, urlunparse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ConfigurationError
from dotenv import load_dotenv
from typing import Optional

# Load environment variables
# Try loading from project root first, then backend directory
import os as os_module
env_path = os_module.path.join(os_module.path.dirname(os_module.path.dirname(__file__)), ".env")
if os_module.path.exists(env_path):
    load_dotenv(env_path)

backend_env = os_module.path.join(os_module.path.dirname(__file__), ".env")
if os_module.path.exists(backend_env):
    load_dotenv(backend_env, override=True)

# Also try loading from current directory
load_dotenv(override=False)

# Global MongoDB client instance
_mongo_client: Optional[MongoClient] = None
_db_name: Optional[str] = None
_client_lock = threading.Lock()


def _is_shutting_down():
    """Check if Python interpreter is shutting down."""
    return not threading.main_thread().is_alive() or sys.is_finalizing()


def get_mongodb_client() -> MongoClient:
    """
    Create and return a MongoDB client instance.
    
    Environment variables required:
        - MONGODB_URI: MongoDB connection string
        
    Returns:
        MongoClient: Configured MongoDB client instance
    
    Raises:
        RuntimeError: If required environment variables are missing or connection fails
    """
    global _mongo_client
    
    # Check if shutting down
    if _is_shutting_down():
        raise RuntimeError("Cannot create MongoDB connection during interpreter shutdown")
    
    # Use lock to prevent race conditions
    with _client_lock:
        if _mongo_client is not None:
            # Verify client is still alive
            try:
                _mongo_client.admin.command('ping')
                return _mongo_client
            except Exception:
                # Client is dead, create a new one
                _mongo_client = None
        
        # Get MongoDB configuration from environment variables
        mongodb_uri = os.getenv("MONGODB_URI")
        
        # Validate required environment variables
        if not mongodb_uri:
            raise RuntimeError("MONGODB_URI is not set in environment. Please set it in your .env file.")
        
        try:
            # Parse the MongoDB URI
            parsed = urlparse(mongodb_uri)
            
            # Check if credentials are already URL-encoded in the connection string
            # If the password contains % (URL encoding), use the URI as-is to avoid double-encoding
            if "@" in parsed.netloc:
                auth_part, host_part = parsed.netloc.rsplit("@", 1)
                if ":" in auth_part:
                    username, password = auth_part.split(":", 1)
                    # Check if password is already URL-encoded (contains %)
                    if "%" in password:
                        # Password is already encoded, use connection string as-is
                        encoded_uri = mongodb_uri
                    else:
                        # Password is not encoded, encode it now
                        from urllib.parse import unquote_plus
                        # Decode first in case of partial encoding, then re-encode properly
                        decoded_username = unquote_plus(username)
                        decoded_password = unquote_plus(password)
                        encoded_username = quote_plus(decoded_username)
                        encoded_password = quote_plus(decoded_password)
                        encoded_netloc = f"{encoded_username}:{encoded_password}@{host_part}"
                        encoded_uri = urlunparse((
                            parsed.scheme,
                            encoded_netloc,
                            parsed.path,
                            parsed.params,
                            parsed.query,
                            parsed.fragment
                        ))
                else:
                    # No password, use as-is
                    encoded_uri = mongodb_uri
            else:
                # No credentials, use as-is
                encoded_uri = mongodb_uri
            
            # Base client options
            client_options = {
                "serverSelectionTimeoutMS": 20000,
                "connectTimeoutMS": 20000,
                "socketTimeoutMS": 30000,
                "maxPoolSize": 10,
                "minPoolSize": 1,
                "maxIdleTimeMS": 45000,
                "retryWrites": True,
                "retryReads": True,
            }
            
            # Add SSL/TLS configuration for MongoDB Atlas using certifi
            if "mongodb.net" in encoded_uri or parsed.scheme == "mongodb+srv":
                try:
                    import certifi
                    client_options.update({
                        "tls": True,
                        "tlsCAFile": certifi.where(),
                    })
                except ImportError:
                    # If certifi is not installed, fall back to allowing invalid certificates
                    client_options.update({
                        "tls": True,
                        "tlsAllowInvalidCertificates": True,
                    })
            
            # Create MongoDB client with configured options
            client = MongoClient(encoded_uri, **client_options)
            
            # Test the connection (with timeout to prevent hanging)
            try:
                client.admin.command('ping')
            except Exception as ping_error:
                client.close()
                raise RuntimeError(f"MongoDB connection test failed: {str(ping_error)}")
            
            _mongo_client = client
            return client
            
        except ConnectionFailure as e:
            raise RuntimeError(f"Failed to connect to MongoDB: {str(e)}")
        except ConfigurationError as e:
            raise RuntimeError(f"MongoDB configuration error: {str(e)}")
        except RuntimeError:
            # Re-raise RuntimeError as-is
            raise
        except Exception as e:
            error_msg = str(e)
            # Check if it's a shutdown-related error
            if "shutdown" in error_msg.lower() or "thread" in error_msg.lower():
                raise RuntimeError(f"Cannot create MongoDB connection: {error_msg}")
            raise RuntimeError(f"Unexpected error connecting to MongoDB: {error_msg}")


def get_database():
    """
    Get the MongoDB database instance.
    
    Environment variables:
        - MONGODB_DB_NAME: Database name (optional, defaults to extracting from URI or 'possystem')
        
    Returns:
        Database: MongoDB database instance
    """
    global _db_name
    
    client = get_mongodb_client()
    
    # Get database name from environment or extract from URI
    if not _db_name:
        db_name = os.getenv("MONGODB_DB_NAME")
        if not db_name:
            # Try to extract from URI, or use default
            uri = os.getenv("MONGODB_URI", "")
            if "mongodb.net/" in uri:
                # Extract database name from URI if present
                parts = uri.split("mongodb.net/")
                if len(parts) > 1:
                    db_part = parts[1].split("?")[0]
                    if db_part:
                        db_name = db_part
            if not db_name:
                db_name = "possystem"  # Default database name
        _db_name = db_name
    
    return client[_db_name]


def get_collection(collection_name: str):
    """
    Get a MongoDB collection.
    
    Args:
        collection_name: Name of the collection
        
    Returns:
        Collection: MongoDB collection instance
    """
    db = get_database()
    return db[collection_name]


def close_mongodb_client():
    """
    Close the MongoDB client connection.
    Call this during application shutdown to clean up resources.
    """
    global _mongo_client
    with _client_lock:
        if _mongo_client is not None:
            try:
                _mongo_client.close()
            except Exception:
                pass  # Ignore errors during shutdown
            finally:
                _mongo_client = None
