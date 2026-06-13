"""Official-compatible API response envelope."""

from typing import Any

SUCCESS = 10000


def ok(data: Any = None, message: str = "success") -> dict:
    return {"code": SUCCESS, "message": message, "data": data}


def err(code: int, message: str) -> dict:
    return {"code": code, "message": message, "data": None}
