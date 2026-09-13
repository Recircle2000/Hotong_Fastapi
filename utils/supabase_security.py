import threading
import time
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)

from auth_config import (
    SupabaseAuthConfig,
    SupabaseAuthConfigurationError,
    get_supabase_auth_config,
)
from schemas.app_auth import CurrentAppUser


bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str = "인증에 실패했습니다") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="인증 서비스를 일시적으로 사용할 수 없습니다",
    )


class CachedJWKResolver:
    """Resolve Supabase signing keys with a short failure backoff."""

    def __init__(
        self,
        jwks_url: str,
        *,
        cache_lifespan_seconds: int = 300,
        failure_backoff_seconds: int = 5,
        timeout_seconds: int = 3,
    ) -> None:
        self._client = PyJWKClient(
            jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=cache_lifespan_seconds,
            timeout=timeout_seconds,
        )
        self._failure_backoff_seconds = failure_backoff_seconds
        self._retry_after = 0.0
        self._last_error: PyJWKClientError | None = None
        self._lock = threading.Lock()

    def get_signing_key_from_jwt(self, token: str) -> Any:
        with self._lock:
            now = time.monotonic()
            if self._last_error is not None and now < self._retry_after:
                raise self._last_error

            try:
                key = self._client.get_signing_key_from_jwt(token)
            except PyJWKClientError as exc:
                self._last_error = exc
                self._retry_after = now + self._failure_backoff_seconds
                raise

            self._last_error = None
            self._retry_after = 0.0
            return key


@lru_cache(maxsize=1)
def get_jwk_resolver() -> CachedJWKResolver:
    config = get_supabase_auth_config()
    return CachedJWKResolver(config.jwks_url)


def get_auth_config_dependency() -> SupabaseAuthConfig:
    try:
        return get_supabase_auth_config()
    except SupabaseAuthConfigurationError as exc:
        raise _service_unavailable() from exc


def get_jwk_resolver_dependency() -> CachedJWKResolver:
    try:
        return get_jwk_resolver()
    except SupabaseAuthConfigurationError as exc:
        raise _service_unavailable() from exc


def _is_school_email(email: object, allowed_domain: str) -> bool:
    if not isinstance(email, str):
        return False
    normalized = email.strip().lower()
    local_part, separator, domain = normalized.partition("@")
    return bool(
        local_part
        and separator
        and "@" not in domain
        and domain == allowed_domain
        and not any(character.isspace() for character in normalized)
    )


def _has_otp_amr(amr: object) -> bool:
    if not isinstance(amr, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("method") == "otp"
        for entry in amr
    )


def verify_supabase_access_token(
    token: str,
    *,
    config: SupabaseAuthConfig,
    resolver: CachedJWKResolver,
) -> CurrentAppUser:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != config.allowed_algorithm:
            raise _unauthorized()

        signing_key = resolver.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[config.allowed_algorithm],
            audience=config.audience,
            issuer=config.issuer,
            leeway=30,
            options={
                "require": [
                    "iss",
                    "aud",
                    "exp",
                    "iat",
                    "sub",
                    "role",
                    "session_id",
                    "email",
                    "is_anonymous",
                    "amr",
                ]
            },
        )
    except HTTPException:
        raise
    except PyJWKClientConnectionError as exc:
        raise _service_unavailable() from exc
    except (InvalidTokenError, PyJWKClientError, ValueError, TypeError) as exc:
        raise _unauthorized() from exc

    if claims.get("role") != "authenticated":
        raise _unauthorized()
    if claims.get("is_anonymous") is not False:
        raise _unauthorized()
    if not _is_school_email(claims.get("email"), config.allowed_email_domain):
        raise _unauthorized()
    if not _has_otp_amr(claims.get("amr")):
        raise _unauthorized()

    try:
        user_id = UUID(str(claims["sub"]))
        UUID(str(claims["session_id"]))
    except (ValueError, TypeError, KeyError) as exc:
        raise _unauthorized() from exc

    return CurrentAppUser(user_id=user_id)


def get_current_app_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    config: SupabaseAuthConfig = Depends(get_auth_config_dependency),
    resolver: CachedJWKResolver = Depends(get_jwk_resolver_dependency),
) -> CurrentAppUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("인증이 필요합니다")

    return verify_supabase_access_token(
        credentials.credentials,
        config=config,
        resolver=resolver,
    )
