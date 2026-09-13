import time
import unittest
from copy import deepcopy
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError

from auth_config import SupabaseAuthConfig
from routers import app_auth
from utils.supabase_security import (
    get_auth_config_dependency,
    get_jwk_resolver_dependency,
)


class _SigningKey:
    def __init__(self, key):
        self.key = key


class _StaticResolver:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _token):
        return _SigningKey(self._key)


class _OfflineResolver:
    def get_signing_key_from_jwt(self, _token):
        raise PyJWKClientConnectionError("offline")


class AppAuthApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = ec.generate_private_key(ec.SECP256R1())
        cls.public_key = cls.private_key.public_key()
        cls.config = SupabaseAuthConfig(
            project_url="https://project.supabase.co",
            issuer="https://project.supabase.co/auth/v1",
            jwks_url=(
                "https://project.supabase.co/auth/v1/.well-known/jwks.json"
            ),
        )

        cls.app = FastAPI()
        cls.app.include_router(app_auth.router)
        cls.app.dependency_overrides[get_auth_config_dependency] = (
            lambda: cls.config
        )
        cls.app.dependency_overrides[get_jwk_resolver_dependency] = (
            lambda: _StaticResolver(cls.public_key)
        )
        cls.client = TestClient(cls.app)

    def setUp(self):
        now = int(time.time())
        self.user_id = uuid4()
        self.claims = {
            "iss": self.config.issuer,
            "aud": "authenticated",
            "exp": now + 3600,
            "iat": now,
            "sub": str(self.user_id),
            "role": "authenticated",
            "session_id": str(uuid4()),
            "email": "student@vision.hoseo.edu",
            "is_anonymous": False,
            "amr": [{"method": "otp", "timestamp": now}],
        }

    def _token(self, claims=None, *, algorithm="ES256", key=None):
        return jwt.encode(
            claims or self.claims,
            key if key is not None else self.private_key,
            algorithm=algorithm,
            headers={"kid": "test-key"},
        )

    def _get(self, token):
        return self.client.get(
            "/api/app-auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    def test_valid_otp_token_returns_uuid_without_email(self):
        response = self._get(self._token())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"user_id": str(self.user_id)})
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_missing_token_returns_401(self):
        response = self.client.get("/api/app-auth/me")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_invalid_claims_are_rejected(self):
        cases = {
            "issuer": {"iss": "https://other.supabase.co/auth/v1"},
            "audience": {"aud": "anon"},
            "role": {"role": "anon"},
            "anonymous": {"is_anonymous": True},
            "email": {"email": "student@vision.hoseo.edu.evil.test"},
            "amr": {"amr": [{"method": "password"}]},
            "subject": {"sub": "not-a-uuid"},
            "session": {"session_id": "not-a-uuid"},
            "expired": {"exp": int(time.time()) - 120},
        }

        for name, changes in cases.items():
            with self.subTest(name=name):
                claims = deepcopy(self.claims)
                claims.update(changes)
                self.assertEqual(self._get(self._token(claims)).status_code, 401)

    def test_non_es256_token_is_rejected(self):
        token = self._token(algorithm="HS256", key="not-the-project-secret")

        self.assertEqual(self._get(token).status_code, 401)

    def test_jwks_connection_failure_returns_503(self):
        self.app.dependency_overrides[get_jwk_resolver_dependency] = (
            lambda: _OfflineResolver()
        )
        try:
            response = self._get(self._token())
        finally:
            self.app.dependency_overrides[get_jwk_resolver_dependency] = (
                lambda: _StaticResolver(self.public_key)
            )

        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
