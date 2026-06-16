"""Async token lifecycle service.

Replaces the legacy synchronous _authenticate() method on RAITClient.
Token and public key are cached per-instance with proactive refresh.
No os.environ writes — credentials live only in the Settings instance.
"""
import logging
import time

import httpx

from ..config import Settings

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, config: Settings) -> None:
        self._config = config
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._public_key_pem: str | None = None

    async def ensure_token(self) -> str:
        """Return a valid bearer token, refreshing proactively if within 30s of expiry."""
        if self._token and time.monotonic() < self._expires_at - 30:
            return self._token

        url = f"{self._config.rait_api_url}/api/model-registry/token/"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                json={
                    "client_id": self._config.rait_client_id,
                    "client_secret": self._config.rait_client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._token = data["access_token"]
        self._expires_at = time.monotonic() + float(data.get("expires_in", 3600))
        logger.debug("Token refreshed; expires in %.0fs", data.get("expires_in", 3600))
        return self._token

    async def get_public_key(self) -> str:
        """Return the registry's RSA public key PEM, fetching and caching on first call.

        The public key is stable for the lifetime of the registry process, so it is
        cached permanently per AuthService instance. All three services
        (EvaluationService, TelemetryService, CalibrationScheduler) previously
        duplicated this fetch independently.
        """
        if self._public_key_pem:
            return self._public_key_pem

        token = await self.ensure_token()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._config.rait_api_url}/api/model-registry/public-key/",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            self._public_key_pem = resp.json()["data"]["public_key"]

        logger.debug("RSA public key fetched and cached from registry")
        return self._public_key_pem

    def invalidate(self) -> None:
        """Force token refresh on next ensure_token() call. Does not clear public key."""
        self._token = None
        self._expires_at = 0.0
