"""One error envelope for every non-streaming response:

    {"error": {"code": "...", "message": "...", "requestId": "...", "details": {}}}

Routers and services raise ApiError; handlers in main.py render the envelope and attach
the request id. Validation (422) is rendered from FastAPI's RequestValidationError."""
from __future__ import annotations
from typing import Any


class ApiError(Exception):
    """A safe, client-facing error. `message` must never contain secrets or raw
    upstream provider bodies."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

    def envelope(self, request_id: str) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "requestId": request_id,
                "details": self.details,
            }
        }


# --- Common constructors -----------------------------------------------------

def unauthorized(message: str = "Missing or invalid credentials") -> ApiError:
    return ApiError(401, "unauthorized", message)


def forbidden(message: str = "Operator key required") -> ApiError:
    return ApiError(403, "forbidden", message)


def upstream_unavailable(code: str, message: str) -> ApiError:
    return ApiError(503, code, message)


def upstream_bad_gateway(code: str, message: str) -> ApiError:
    return ApiError(502, code, message)
