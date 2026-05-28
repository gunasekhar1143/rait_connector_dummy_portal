"""Router for /api/model-registry/token/: OAuth2-style token issuance."""
import secrets
import logging

from fastapi import APIRouter, HTTPException, Request

from ..models.schemas import TokenRequest, TokenResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/token/")
async def get_token(body: TokenRequest, request: Request) -> TokenResponse:
    state = request.app.state.registry_state
    # Accept any non-empty credentials for PoC
    if not body.client_id or not body.client_secret:
        raise HTTPException(status_code=401, detail="client_id and client_secret required")

    token = secrets.token_urlsafe(32)
    state.store_token(token, body.client_id)
    logger.info("Issued token for client_id=%s", body.client_id)
    return TokenResponse(access_token=token)
