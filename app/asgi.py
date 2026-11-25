"""Uvicorn entry point: `uvicorn app.asgi:app`. Kept out of main.py so the module
stays importable by tests without a configured environment."""
from .main import create_app

app = create_app()
