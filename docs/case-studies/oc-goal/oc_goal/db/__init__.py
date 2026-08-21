"""The database connection owned by the oc-goal application."""

from .schema import connect, db_path

__all__ = ["connect", "db_path"]
