import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from sqlalchemy import insert

from .db import now, sessions

passwords = PasswordHasher()


def verify_password(stored, supplied):
    try:
        return passwords.verify(stored, supplied)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_tokens(db, user_id, client_kind, secret, family=None):
    current = now()
    access = jwt.encode(
        {
            "sub": user_id,
            "iat": current,
            "exp": current + timedelta(minutes=15),
            "iss": "shadowweave",
            "aud": "shadowweave-api",
        },
        secret,
        algorithm="HS256",
    )
    refresh = secrets.token_urlsafe(48)
    db.execute(
        insert(sessions).values(
            user_id=user_id,
            token_hash=token_hash(refresh),
            family_id=family or str(uuid4()),
            expires_at=current + timedelta(days=7),
            client_kind=client_kind,
        )
    )
    return {"access_token": access, "token_type": "bearer", "expires_in": 900}, refresh
