"""API errors → envelope responses. Raise ApiError anywhere in a route."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from brain import BrainError, BrandSpaceNotFound, ProposalAlreadyDecided, ProposalNotFound
from brain.providers import ProviderError
from server.envelope import NextAction, error

log = logging.getLogger("server")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, field: str | None = None,
                 instructions: str = "", next_actions: list[NextAction] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.field = field
        self.instructions = instructions
        self.next_actions = next_actions or []


def not_found(what: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


_BRAIN_ERRORS: dict[type[BrainError], tuple[int, str]] = {
    BrandSpaceNotFound: (404, "not_found"),
    ProposalNotFound: (404, "not_found"),
    ProposalAlreadyDecided: (409, "already_decided"),
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(
            error(e.code, e.message, field=e.field, instructions=e.instructions,
                  next_actions=e.next_actions),
            status_code=e.status,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found",
                405: "method_not_allowed"}.get(e.status_code, "http_error")
        return JSONResponse(error(code, str(e.detail)), status_code=e.status_code,
                            headers=getattr(e, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse(
            error("invalid_request", first.get("msg", "invalid request"), field=loc or None),
            status_code=422,
        )

    @app.exception_handler(BrainError)
    async def _brain(_: Request, e: BrainError):
        status, code = _BRAIN_ERRORS.get(type(e), (400, "brain_error"))
        return JSONResponse(error(code, str(e) or code), status_code=status)

    @app.exception_handler(ProviderError)
    async def _provider(_: Request, e: ProviderError):
        log.warning("provider error: %s", e)
        return JSONResponse(
            error("provider_unavailable", f"The AI provider failed: {e}",
                  instructions="This is a temporary server-side problem. Retry the same "
                               "command in a minute; the founder's answer was not lost."),
            status_code=502,
        )
