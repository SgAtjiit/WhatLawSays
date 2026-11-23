"""Firebase sign-in for the API.

The browser signs in with Firebase and sends its ID token as a Bearer header.
Verifying that token needs only the project ID: the library checks the
signature against Google's published keys, so the server holds no
service-account secret. With FIREBASE_AUTH_EMULATOR_HOST set, the same call
accepts tokens from the local Auth emulator instead, which is how the test
suites run sign-in without touching a real project.
"""

from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException
from starlette.concurrency import run_in_threadpool

from src.config import settings


@dataclass(frozen=True)
class User:
    uid: str
    email: Optional[str] = None
    name: Optional[str] = None


_firebase_app = None


def _app():
    global _firebase_app
    if _firebase_app is None:
        if not settings.FIREBASE_PROJECT_ID:
            raise HTTPException(
                status_code=503,
                detail="Sign-in is not configured on this server (FIREBASE_PROJECT_ID is unset).",
            )
        import firebase_admin

        _firebase_app = firebase_admin.initialize_app(
            options={"projectId": settings.FIREBASE_PROJECT_ID}, name="whatlawsays"
        )
    return _firebase_app


def _verify(token: str) -> dict:
    from firebase_admin import auth

    return auth.verify_id_token(token, app=_app())


async def require_user(authorization: Optional[str] = Header(None)) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    from firebase_admin import auth

    _app()
    try:
        claims = await run_in_threadpool(_verify, token.strip())
    except auth.CertificateFetchError:
        raise HTTPException(
            status_code=503,
            detail="Sign-in could not be checked right now. Try again in a moment.",
        )
    except (ValueError, auth.InvalidIdTokenError):
        # Expired and revoked tokens are subclasses of InvalidIdTokenError.
        raise HTTPException(
            status_code=401,
            detail="Your session has expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provider = (claims.get("firebase") or {}).get("sign_in_provider")
    if provider == "password" and not claims.get("email_verified"):
        raise HTTPException(
            status_code=403,
            detail="Verify your email address to continue. Check your inbox for the link.",
        )

    return User(uid=claims["uid"], email=claims.get("email"), name=claims.get("name"))
