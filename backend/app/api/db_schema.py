from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from sqlalchemy import inspect

from ..core.config import engine, settings

router = APIRouter(prefix="/api/db", tags=["debug"], include_in_schema=True)


def _serialize_columns(inspector, table_name: str) -> List[Dict[str, Any]]:
    columns: List[Dict[str, Any]] = []
    for column in inspector.get_columns(table_name):
        default = column.get("default")
        columns.append(
            {
                "name": column.get("name"),
                "type": str(column.get("type")),
                "nullable": bool(column.get("nullable", True)),
                "default": str(default) if default is not None else None,
                "primary_key": bool(column.get("primary_key", False)),
            }
        )
    return columns


def _serialize_foreign_keys(inspector, table_name: str) -> List[Dict[str, Any]]:
    fks: List[Dict[str, Any]] = []
    for fk in inspector.get_foreign_keys(table_name):
        fks.append(
            {
                "name": fk.get("name"),
                "constrained_columns": fk.get("constrained_columns", []),
                "referred_table": fk.get("referred_table"),
                "referred_columns": fk.get("referred_columns", []),
                "referred_schema": fk.get("referred_schema"),
            }
        )
    return fks


def _serialize_indexes(inspector, table_name: str) -> List[Dict[str, Any]]:
    idx: List[Dict[str, Any]] = []
    for index in inspector.get_indexes(table_name):
        idx.append(
            {
                "name": index.get("name"),
                "column_names": index.get("column_names", []),
                "unique": bool(index.get("unique", False)),
            }
        )
    return idx


@router.get("/schema", summary="List database tables and columns")
def get_db_schema(include_views: bool = True) -> Dict[str, Any]:
    """Return the SQLite schema (tables + columns) as JSON for Swagger."""
    with engine.connect() as connection:
        inspector = inspect(connection)

        tables: List[Dict[str, Any]] = []
        for table_name in sorted(inspector.get_table_names()):
            tables.append(
                {
                    "name": table_name,
                    "columns": _serialize_columns(inspector, table_name),
                    "primary_key": inspector.get_pk_constraint(table_name).get(
                        "constrained_columns", []
                    ),
                    "foreign_keys": _serialize_foreign_keys(inspector, table_name),
                    "indexes": _serialize_indexes(inspector, table_name),
                }
            )

        views: List[Dict[str, Any]] = []
        if include_views:
            for view_name in sorted(inspector.get_view_names()):
                views.append(
                    {
                        "name": view_name,
                        "definition": inspector.get_view_definition(view_name),
                        "columns": _serialize_columns(inspector, view_name),
                    }
                )

    return {
        "database_url": settings.DATABASE_URL,
        "tables": tables,
        "views": views,
        "include_views": include_views,
    }
