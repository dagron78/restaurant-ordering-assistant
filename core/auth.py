"""
Role authentication (Phase A · issue #50).

Two shared passwords, one per role:

    admin — everything, including every configuration surface
    app   — the ordering round only

Hashes live in the settings table (app_password_hash /
admin_password_hash) and are written ONLY through this module. No
Streamlit imports: unit-testable without the UI stack.

First-run contract: until an admin hash exists the app is UNCONFIGURED
and must offer setup, not open access. This deliberately supersedes
issue #37's open-access-with-warning choice — see docs/SPEC.md and the
Phase A PR notes.
"""

from typing import Optional

from .config import Config
from .security import hash_password, verify_password
from .settings import get_setting, is_configured as _store_is_configured

ROLES = ("admin", "app")


def is_configured(db=None) -> bool:
    """True once an admin password exists. Until then: first-run."""
    return _store_is_configured(db=db)


def authenticate(candidate: str, db=None) -> Optional[str]:
    """
    Return the role the candidate password belongs to, else None.

    The admin hash is checked first so an admin can always sign in even
    if both roles were given the same passphrase.
    """
    if not candidate:
        return None
    admin_hash = get_setting("admin_password_hash", db=db)
    if admin_hash and verify_password(candidate, admin_hash):
        return "admin"
    app_hash = get_setting("app_password_hash", db=db)
    if app_hash and verify_password(candidate, app_hash):
        return "app"
    return None


def set_password(role: str, plaintext: str, db=None) -> None:
    """Write a role's password hash. First-run and admin UI both use this."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    if not plaintext:
        raise ValueError("Password must not be empty")
    from .settings import set_settings

    set_settings({f"{role}_password_hash": hash_password(plaintext)}, db=db)


def change_password(role: str, new_plaintext: str,
                    current_plaintext: str = None, db=None) -> bool:
    """
    Change a role's password, verifying the CURRENT one first.

    Returns False when the current password does not match (or is
    required but missing). Never stores plaintext anywhere.
    """
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    stored = get_setting(f"{role}_password_hash", db=db)
    if stored or current_plaintext is not None:
        if not current_plaintext or \
                authenticate(current_plaintext, db=db) != role:
            return False
    set_password(role, new_plaintext, db=db)
    return True


def bootstrap_initial_admin(db=None) -> bool:
    """
    Seed the admin password from INITIAL_ADMIN_PASSWORD exactly once.

    Installer places it in .env; first boot adopts it as the admin
    password. Subsequent boots are no-ops (a hash already exists), and a
    first-run setup page remains available whenever nothing is configured.
    """
    if _store_is_configured(db=db):
        return False
    initial = Config.initial_admin_password()
    if not initial:
        return False
    set_password("admin", initial, db=db)
    return True
