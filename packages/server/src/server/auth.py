"""Bearer-token auth. Tokens are random, shown once, stored as sha256 hashes."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from server.errors import ApiError
from server.models import ApiToken, Brand, User, now
from server.services import Services

TOKEN_PREFIX = "vybd_"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def services(request: Request) -> Services:
    return request.app.state.services


def get_session(svc: Annotated[Services, Depends(services)]) -> Iterator[Session]:
    with svc.session_factory() as s:
        yield s


SvcDep = Annotated[Services, Depends(services)]
SessionDep = Annotated[Session, Depends(get_session)]


def _unauthorized(msg: str) -> ApiError:
    return ApiError(
        401, "unauthorized", msg,
        instructions="Run `vybd signup --email <email>` (or set a valid token) and retry.",
    )


def current_user(request: Request, s: SessionDep) -> User:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _unauthorized("Missing bearer token")
    row = s.scalars(
        select(ApiToken).where(ApiToken.token_hash == hash_token(token.strip()),
                               ApiToken.revoked_at.is_(None))
    ).first()
    if row is None:
        raise _unauthorized("Invalid or revoked token")
    row.last_used_at = now()
    user = s.get(User, row.user_id)
    s.commit()
    if user is None:
        raise _unauthorized("Token user no longer exists")
    return user


UserDep = Annotated[User, Depends(current_user)]


def is_admin(user: User, svc: Services) -> bool:
    return user.email.lower() in svc.settings.admin_emails


def owned_brand(s: Session, user: User, brand_id: str) -> Brand:
    try:
        bid = uuid.UUID(brand_id)
    except ValueError:
        raise ApiError(404, "not_found", "brand not found") from None
    brand = s.get(Brand, bid)
    if brand is None or brand.owner_id != user.id:
        raise ApiError(404, "not_found", "brand not found",
                       instructions="Run `vybd brand list` to see your brands.")
    return brand
