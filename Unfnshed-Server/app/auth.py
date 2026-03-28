"""API key authentication."""

from fastapi import Header, HTTPException, status

from .config import get_settings


async def verify_api_key(x_api_key: str = Header(..., description="API key for authentication")):
    """Verify the API key from request header."""
    settings = get_settings()
    valid_keys = settings.api_key_list

    if not valid_keys:
        # No keys configured - allow all requests (development mode)
        return x_api_key

    if x_api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    return x_api_key
