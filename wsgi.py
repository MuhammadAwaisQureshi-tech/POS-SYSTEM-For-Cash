"""
WSGI entry point for production deployment.
This file is used by Gunicorn to serve the Flask application.
"""
from app import create_app

# Create the Flask application instance
app = create_app()

if __name__ == "__main__":
    # This is only for local testing
    app.run()

