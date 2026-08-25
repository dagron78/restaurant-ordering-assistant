"""
Settings store (Phase A · issue #50).

Operator-changeable configuration lives in the `settings` table, written
through the admin UI, effective on the next page run — no restart.

Three layers:

1. SETTING_DEFS  — the typed registry: every managed key with its default,
   type, whether it is a secret, and a human label for the admin UI. This
   is the single source of truth for what is configurable.
2. get_setting() — DB row first, registry default second. The environment
   is NOT consulted here: only bootstrap keys (database path, initial
   admin password) still come from .env, and they are handled in
   core/config.py, not by this module.
3. set_settings() — upsert rows, then invalidate Streamlit's resource and
   data caches. Invalidation is the belt to the suspenders of reading
   config at use time: even an object that captured a value survives only
   until the next settings write.

No Streamlit import at module scope: this must stay unit-testable without
the UI stack (same rule as core/security.py).
"""

import logging
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# key -> (default, type, secret, label)
# Defaults mirror the pre-Phase-A .env.example so an unconfigured install
# behaves exactly as before.
SETTING_DEFS: Dict[str, tuple] = {
    # AI
    "GOOGLE_API_KEY":     ("", str, True, "Gemini API key"),
    "GEMINI_MODEL_FLASH": ("gemini-2.5-flash", str, False, "Flash model"),
    "GEMINI_MODEL_PRO":   ("gemini-2.5-pro", str, False, "Pro model"),
    # Email intake
    "EMAIL_USER":           ("", str, True, "Mailbox user"),
    "EMAIL_PASS":           ("", str, True, "Mailbox password"),
    "EMAIL_IMAP_SERVER":    ("imap.gmail.com", str, False, "IMAP host"),
    "EMAIL_CHECK_INTERVAL": (8, int, False, "Email check interval (hours)"),
    # File locations (relative to the app directory)
    "PREFERENCES_PATH": ("data/preferences.txt", str, False, "Preferences file path"),
    "SESSIONS_PATH":    ("data/sessions", str, False, "Vendor sessions path"),
    "TEMP_PATH":        ("data/temp", str, False, "Upload temp path"),
    # Scheduling
    "SCRAPE_DAY":        (0, int, False, "Scrape day (0=Mon .. 6=Sun)"),
    "SCRAPE_HOUR":       (4, int, False, "Scrape hour (0-23)"),
    "SCRAPE_DELAY_SECS": (2.0, float, False, "Pause between scrapes (secs)"),
    # Trend analysis thresholds
    "TREND_DAYS":     (30, int, False, "Rolling average window (days)"),
    "SPIKE_THRESHOLD": (0.10, float, False, "Spike threshold (fraction)"),
    "DEAL_THRESHOLD":  (-0.10, float, False, "Deal threshold (fraction)"),
    # Ordering round (Phase C): plan-after = sheet -> Send -> plan ->
    # override -> confirm (default, matches working from par);
    # plan_during = prices inline while entering (the Order Guide).
    "ORDER_MODE": ("plan_after", str, False, "Ordering mode"),
}

# Credential hashes live in the same table but are not operator-editable
# rows in the admin UI; they are written only through the password-change
# and first-run flows.
AUTH_KEYS = ("app_password_hash", "admin_password_hash")

MANAGED_KEYS = frozenset(SETTING_DEFS) | frozenset(AUTH_KEYS)

# Keys whose values are filesystem locations stored relative to BASE_DIR.
# They resolve to absolute Paths so historical call sites
# (Config.TEMP_PATH.mkdir() etc.) keep working unchanged.
PATH_KEYS = frozenset(
    {"PREFERENCES_PATH", "SESSIONS_PATH", "TEMP_PATH"})


def _coerce(key: str, raw: Optional[str], default: Any, typ: type) -> Any:
    """TEXT column -> typed value; unparseable falls back to the default."""
    if raw is None:
        return default
    if typ is str:
        return raw
    try:
        return typ(raw)
    except (TypeError, ValueError):
        # The value itself is never logged — it may be a secret.
        log.warning("Setting %s is unparseable as %s; using default",
                    key, typ.__name__)
        return default


def _open(db):
    """Connection for a read/write, or None when no database exists yet.

    A bare read against a not-yet-created database must answer with
    defaults, never create files as a side effect.
    """
    if db is not None:
        return db.get_connection()
    from .config import Config

    if not Config.DATABASE_PATH.exists():
        return None
    from .database import Database

    return Database().get_connection()


def get_setting(key: str, db=None) -> Any:
    """Read one setting: stored row first, registry default second."""
    if key not in MANAGED_KEYS:
        raise KeyError(f"Unknown setting: {key}")

    default, typ, _secret, _label = SETTING_DEFS.get(
        key, ("", str, True, key))
    try:
        conn = _open(db)
        if conn is None:
            value = default
        else:
            with conn as c:
                row = c.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (key,)).fetchone()
            value = _coerce(key, row["value"] if row else None, default, typ)
    except Exception:
        # Uninitialized or mid-migration database — defaults apply.
        value = default
    if key in PATH_KEYS:
        from pathlib import Path
        from .config import Config

        p = Path(value)
        return p if p.is_absolute() else Config.BASE_DIR / p
    return value


def get_all_settings(db=None) -> Dict[str, Any]:
    """Every managed setting resolved (used by the admin page)."""
    return {key: get_setting(key, db=db) for key in SETTING_DEFS}


def set_settings(updates: Dict[str, Any], db=None) -> None:
    """
    Upsert settings, then invalidate cached resources.

    Values are stringified here; hashing of passwords is the caller's job
    (only *_hash keys may hold hash text — plain passwords must never be
    passed to this function).
    """
    unknown = [k for k in updates if k not in MANAGED_KEYS]
    if unknown:
        raise KeyError(f"Unknown settings: {unknown}")

    rows = [(k, str(v)) for k, v in updates.items()]
    conn = _open(db)
    if conn is None:
        raise FileNotFoundError(
            "Cannot save settings: the database does not exist yet. "
            "Complete first-run initialization first.")
    with conn as c:
        c.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = CURRENT_TIMESTAMP",
            rows,
        )
    _invalidate_ui_caches()


def is_configured(db=None) -> bool:
    """True once an admin password hash exists — i.e. first-run is done.

    Tolerant of a database that does not exist yet: unconfigured is the
    honest answer before first boot, not an error.
    """
    try:
        conn = _open(db)
        if conn is None:
            return False
        with conn as c:
            row = c.execute(
                "SELECT value FROM settings WHERE key = 'admin_password_hash'"
            ).fetchone()
    except Exception:
        return False
    return bool(row and row["value"])


def _invalidate_ui_caches() -> None:
    """
    Drop every st.cache_resource / st.cache_data entry in this process.

    A cached object that captured a config value must not outlive the
    write that changed it. Guarded so workers and bare pytest (no
    Streamlit runtime) pass through harmlessly.
    """
    try:
        import streamlit as st

        st.cache_resource.clear()
        st.cache_data.clear()
    except Exception:                                   # pragma: no cover
        log.debug("Cache invalidation skipped (no Streamlit runtime)")
