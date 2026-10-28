import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status

from core.config import settings


@dataclass(frozen=True)
class Identity:
    """Who is calling. user_id is None for guests."""

    user_id: str | None

    @property
    def is_guest(self) -> bool:
        return self.user_id is None


def get_identity(
    x_user_id: str | None = Header(default=None),
    x_internal_secret: str | None = Header(default=None),
) -> Identity:
    """
    The Next.js server verifies the NextAuth session, then sends X-User-Id and
    X-Internal-Secret. No X-User-Id means a guest. An X-User-Id without a valid
    secret is rejected, so a browser can never impersonate a user directly.
    """
    user_id = (x_user_id or "").strip()
    if not user_id:
        return Identity(user_id=None)

    expected = settings.internal_secret
    provided = x_internal_secret or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal credentials.",
        )
    return Identity(user_id=user_id[:200])