"""
Supabase client configuration and initialization.
This module handles connection to Supabase database using the service_role key.
"""
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Try to import ClientOptions if available, otherwise use basic client
# ClientOptions provides additional configuration options for newer supabase-py versions
try:
    from supabase.client import ClientOptions
    HAS_CLIENT_OPTIONS = True
except ImportError:
    HAS_CLIENT_OPTIONS = False

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


def get_supabase_client() -> Client:
    """
    Create and return a Supabase client using the service_role key.
    
    The service_role key bypasses Row Level Security (RLS) policies,
    allowing the backend to perform operations without user authentication.
    
    Environment variables required:
        - SUPABASE_URL: Your Supabase project URL
        - SUPABASE_SERVICE_ROLE_KEY: Service role key (secret, not anon key)
    
    Returns:
        Client: Configured Supabase client instance
    
    Raises:
        RuntimeError: If required environment variables are missing or invalid
    """
    # Get Supabase configuration from environment variables
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
    
    # Validate required environment variables
    if not url:
        raise RuntimeError("SUPABASE_URL is not set in environment")
    if not service_key:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not set in environment")
    
    # Verify service_role key format (should start with 'eyJ' and be a JWT)
    if not service_key.startswith("eyJ"):
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY appears to be invalid. "
            "Make sure you're using the SERVICE_ROLE key (secret), not the anon key. "
            "Get it from: Supabase Dashboard → Settings → API → service_role key (secret)"
        )
    
    # Create client with service_role key
    # The service_role key should bypass RLS automatically
    if HAS_CLIENT_OPTIONS:
        # Use ClientOptions for newer supabase-py versions
        client_options = ClientOptions(
            auto_refresh_token=False,  # No need for token refresh with service_role
            persist_session=False,     # No session persistence needed
        )
        client = create_client(
            supabase_url=url,
            supabase_key=service_key,
            options=client_options
        )
    else:
        # Fallback for older supabase-py versions
        client = create_client(
            supabase_url=url,
            supabase_key=service_key
        )
    
    return client



