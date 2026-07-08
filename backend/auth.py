"""
AI Disaster Response Coordinator — Authentication
JWT-based auth with role-based access control (authority / ngo / civilian).
"""

import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from backend.config import settings
from backend.database import get_db
from backend.models import UserDB

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Bcrypt truncates passwords at 72 bytes. We pre-hash overlong passwords with
# SHA-256 (salted) so any length is accepted while still using bcrypt for the
# slow, salted final hash. This matches the common "bcrypt(sha256(pw))" pattern.
_BCRYPT_MAX_BYTES = 72
_LEGACY_SALT = "adrc_salt_2026_"


def _pre_hash(password: str) -> str:
    """Reduce an arbitrarily long password to a bcrypt-safe string."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _legacy_sha256(password: str) -> str:
    """Legacy SHA-256 hash used only for recognizing old password hashes."""
    return hashlib.sha256(f"{_LEGACY_SALT}{password}".encode()).hexdigest()


def _is_legacy_sha256(hashed_password: str) -> bool:
    """Detect the pre-bcrypt SHA-256 scheme (64-char hex digest, no $ prefix)."""
    return (
        len(hashed_password) == 64
        and not hashed_password.startswith("$")
        and all(c in "0123456789abcdef" for c in hashed_password)
    )


def hash_password(password: str) -> str:
    """Hash a password using bcrypt (preferred)."""
    payload = password.encode("utf-8")
    if len(payload) > _BCRYPT_MAX_BYTES:
        payload = _pre_hash(password).encode("utf-8")
    return bcrypt.hashpw(payload, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a stored hash.

    Accepts both bcrypt hashes and legacy SHA-256 hashes (recognized by their
    64-char hex format). Legacy hashes are transparently re-hashed to bcrypt
    by the login handler on the next successful login.
    """
    if not hashed_password:
        return False
    if _is_legacy_sha256(hashed_password):
        # Legacy SHA-256 hash — constant-time compare.
        return hmac.compare_digest(_legacy_sha256(plain_password), hashed_password)
    try:
        payload = plain_password.encode("utf-8")
        if len(payload) > _BCRYPT_MAX_BYTES:
            payload = _pre_hash(plain_password).encode("utf-8")
        return bcrypt.checkpw(payload, hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[UserDB]:
    """Returns current user or None if no valid token."""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    username = payload.get("sub")
    if username is None:
        return None
    user = db.query(UserDB).filter(UserDB.username == username).first()
    return user


async def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer()),
    db: Session = Depends(get_db),
) -> UserDB:
    """Requires valid authentication — raises 401 if not."""
    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_role(*roles):
    """Dependency factory — checks user has one of the specified roles."""
    async def role_checker(user: UserDB = Depends(require_auth)):
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(roles)}"
            )
        return user
    return role_checker
