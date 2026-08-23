"""
Security helpers shared across the app.

Kept in core/ (no Streamlit imports) so the logic is unit-testable
without pulling in the UI stack.
"""

import base64
import hmac
import hashlib
import secrets

# scrypt parameters. Chosen so a verification costs tens of milliseconds:
# real cost for an attacker, invisible in a login form and cheap enough
# that the test suite can exercise auth heavily.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1


def hash_password(password: str) -> str:
    """
    Hash a password for storage in the settings table.

    Returns a self-describing string:
        scrypt$<n>$<r>$<p>$<salt b64>$<derived key b64>
    Parameters travel inside the hash so they can be raised later without
    a migration.
    """
    if not password:
        raise ValueError("Cannot hash an empty password")
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def verify_password(candidate: str, stored: str) -> bool:
    """Check a candidate against a stored hash. Constant-time on digest."""
    if not candidate or not stored:
        return False
    try:
        scheme, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(dk_b64)
        got = hashlib.scrypt(
            candidate.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        # Malformed stored hash: fail closed.
        return False
    return hmac.compare_digest(got, expected)


def password_matches(candidate: str, expected: str) -> bool:
    """Constant-time comparison of an entered and configured password."""
    if not expected:
        return False
    return hmac.compare_digest(
        (candidate or '').encode('utf-8'),
        expected.encode('utf-8'),
    )
