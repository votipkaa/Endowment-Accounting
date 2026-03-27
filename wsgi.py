"""
WSGI entry point for production deployment (Render, Gunicorn, etc.)
"""
import sys
import os

# Add the app directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run()
