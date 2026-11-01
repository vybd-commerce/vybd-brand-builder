from __future__ import annotations

import re

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from server.auth import SessionDep, SvcDep, UserDep, hash_token, is_admin, new_token
from server.envelope import action, ok
from server.errors import ApiError
from server.models import ApiToken, Brand, User

router = APIRouter(prefix="/v1", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    email: str = Field(max_length=320)
    display_name: str | None = Field(default=None, max_length=255)


def user_out(u: User, svc, brand_count: int | None = None) -> dict:
    out = {"id": str(u.id), "email": u.email, "display_name": u.display_name,
           "is_admin": is_admin(u, svc)}
    if brand_count is not None:
        out["brand_count"] = brand_count
    return out


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, s: SessionDep, svc: SvcDep) -> dict:
    """# STUB: no email verification or login flow in v0 — one signup per email."""
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(422, "invalid_email", "That doesn't look like an email address",
                       field="email")
    if s.scalars(select(User).where(User.email == email)).first():
        raise ApiError(409, "email_taken", "An account with this email already exists",
                       field="email",
                       instructions="v0 has no login flow. Use the token already saved in "
                                    "~/.vybd/config.toml, or sign up with a different email.")
    user = User(email=email, display_name=(body.display_name or email.split("@")[0]).strip())
    s.add(user)
    s.flush()
    token = new_token()
    s.add(ApiToken(user_id=user.id, token_hash=hash_token(token), label="signup"))
    s.commit()
    return ok(
        {"user": user_out(user, svc), "token": token},
        instructions="Account created. The token is shown only once; the CLI stores it "
                     "automatically. Next, create a brand for the founder.",
        next_actions=[action("brand.create", name="Brand name")],
    )


@router.get("/me")
def me(user: UserDep, s: SessionDep, svc: SvcDep) -> dict:
    count = s.scalar(select(func.count()).select_from(Brand).where(Brand.owner_id == user.id))
    nxt = [action("brand.list")] if count else [action("brand.create", name="Brand name")]
    return ok({"user": user_out(user, svc, brand_count=count or 0)}, next_actions=nxt)
