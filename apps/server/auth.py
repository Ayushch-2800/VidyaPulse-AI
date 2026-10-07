import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from storage_utils import supabase

security = HTTPBearer()


class AuthenticatedUser(BaseModel):
    id: str
    email: str
    role: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> AuthenticatedUser:
    # Sanitize token to remove accidental whitespaces, quotes, or padding artifacts
    token = credentials.credentials.strip().strip('"').strip("'")

    try:
        # Use Supabase's native auth server to verify the token securely
        response = supabase.auth.get_user(token)

        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Supabase token.",
            )

        user = response.user

        # Safely extract user attributes regardless of object or dict structure
        user_id = getattr(user, "id", None) or (
            user.get("id") if isinstance(user, dict) else None
        )
        email = getattr(user, "email", "") or (
            user.get("email", "") if isinstance(user, dict) else ""
        )
        role = getattr(user, "role", "authenticated") or (
            user.get("role", "authenticated")
            if isinstance(user, dict)
            else "authenticated"
        )

        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user identifier",
            )

        return AuthenticatedUser(id=str(user_id), email=str(email), role=str(role))

    except HTTPException:
        raise
    except Exception as e:
        print(f"[AUTH ERROR]: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication error: {str(e)}",
        )
