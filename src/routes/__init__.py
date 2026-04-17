"""FastAPI routers."""

from src.routes import health, ingest, query

__all__ = ["health", "ingest", "query"]
