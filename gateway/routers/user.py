"""User / auth stub routes."""

from fastapi import APIRouter

from gateway.config import settings
from gateway.response import ok

router = APIRouter()


@router.get("/v1/users/balance")
def get_balance():
    return ok(
        {
            "user_id": "gateway-local",
            "nickname": "Gateway User",
            "mobile": "138****0000",
            "balance": settings.default_balance,
            "company_name": "Self-hosted Gateway",
        }
    )


@router.post("/v1/users/sign_in")
def sign_in(body: dict):
    return ok(
        {
            "access_token": "gateway-token",
            "expire": 9999999999,
            "user_id": "gateway-local",
            "nickname": body.get("username", "user"),
            "uuid": "gateway-uuid",
            "company_name": "Self-hosted Gateway",
        }
    )
