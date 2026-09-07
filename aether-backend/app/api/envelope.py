"""Response envelope shared by all routers.

  reads  → {"success": true, "data": ...}
  writes → flat object with "success": true
  errors → {"success": false, "error": {code, message, retryable}}
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any) -> dict:
    return {"success": True, "data": data}


def error_response(code: str, message: str, status: int, retryable: bool = False) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "success": False,
            "error": {"code": code, "message": message, "retryable": retryable},
        },
    )
