"""Phase A configuration-surface core tests (issue #50).

The named gates of this phase:

- test_config_reflects_database_change_after_import — Config must be a
  live lookup, not import-time constants. Mutant: revert any managed
  attribute to eager os.getenv and THIS dies.
- Settings round-trips through the store, typed, with defaults when the
  database is empty or missing entirely.
"""

import pytest

from core.config import Config
from core.security import hash_password, verify_password
from core.settings import (
    MANAGED_KEYS,
    SETTING_DEFS,
    get_all_settings,
    get_setting,
    is_configured,
    set_settings,
)


@pytest.fixture()
def live_db(tmp_path, monkeypatch):
    """Point Config.DATABASE_PATH at an initialized temp database so the
    metaclass lookups resolve through it."""
    from core.database import Database

    path = tmp_path / "live.db"
    monkeypatch.setattr(Config, "DATABASE_PATH", path)
    Database().init_database()
    return Database()


# ---- the named gate ---------------------------------------------------------

def test_config_reflects_database_change_after_import(live_db):
    """Import-time constants would bake 4 here forever; a live lookup must
    see the new row on the very next attribute read."""
    assert Config.SCRAPE_HOUR == 4                 # registry default
    set_settings({"SCRAPE_HOUR": 9}, db=live_db)
    assert Config.SCRAPE_HOUR == 9                 # no restart, no reimport


def test_config_threshold_change_visible_immediately(live_db):
    set_settings({"SPIKE_THRESHOLD": 0.25}, db=live_db)
    assert Config.SPIKE_THRESHOLD == pytest.approx(0.25)
    set_settings({"DEAL_THRESHOLD": -0.3}, db=live_db)
    assert Config.DEAL_THRESHOLD == pytest.approx(-0.3)


# ---- store mechanics --------------------------------------------------------

def test_get_setting_defaults_when_row_missing(live_db):
    assert get_setting("EMAIL_CHECK_INTERVAL", db=live_db) == 8
    assert get_setting("GOOGLE_API_KEY", db=live_db) == ""


def test_get_setting_survives_missing_database(tmp_path, monkeypatch):
    """No file at all must answer with defaults, not raise — first boot
    order depends on it."""
    monkeypatch.setattr(Config, "DATABASE_PATH", tmp_path / "absent.db")
    assert get_setting("SCRAPE_DAY") == 0


def test_typed_roundtrip(live_db):
    set_settings({
        "EMAIL_CHECK_INTERVAL": 12,
        "SCRAPE_DELAY_SECS": 3.5,
        "GEMINI_MODEL_FLASH": "gemini-2.0-flash",
        "TREND_DAYS": 45,
    }, db=live_db)
    assert get_setting("EMAIL_CHECK_INTERVAL", db=live_db) == 12
    assert get_setting("SCRAPE_DELAY_SECS", db=live_db) == pytest.approx(3.5)
    assert get_setting("GEMINI_MODEL_FLASH", db=live_db) == "gemini-2.0-flash"
    assert get_setting("TREND_DAYS", db=live_db) == 45


def test_unparseable_value_falls_back_to_default(live_db):
    """A hand-mangled row ('abc' in an int column) degrades to the default
    instead of crashing every page that reads it."""
    with live_db.get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES "
            "('EMAIL_CHECK_INTERVAL', 'abc')")
    assert get_setting("EMAIL_CHECK_INTERVAL", db=live_db) == 8


def test_unknown_key_rejected_read_and_write(live_db):
    with pytest.raises(KeyError):
        get_setting("NOT_A_SETTING", db=live_db)
    with pytest.raises(KeyError):
        set_settings({"NOT_A_SETTING": "x"}, db=live_db)


def test_path_settings_resolve_to_absolute_paths(live_db):
    temp = get_setting("TEMP_PATH", db=live_db)
    assert temp.is_absolute()
    assert temp == Config.BASE_DIR / "data" / "temp"
    # And the historical call-site contract holds:
    assert hasattr(temp, "mkdir")


def test_auth_hashes_live_in_same_store(live_db):
    assert not is_configured(db=live_db)
    set_settings({"admin_password_hash": hash_password("first-run!")}, db=live_db)
    assert is_configured(db=live_db)
    # Hash keys participate in the same unknown-key guard:
    with pytest.raises(KeyError):
        set_settings({"app_password": "plaintext-never"}, db=live_db)


def test_plain_password_never_stored():
    """Guard the docstring promise: only *_hash keys may hold credentials,
    and there is no 'password' setting without the suffix."""
    for key in MANAGED_KEYS:
        assert not (key.endswith("password") and not key.endswith("_hash")), key
    assert "APP_PASSWORD" not in SETTING_DEFS or \
        SETTING_DEFS["APP_PASSWORD"][2] is True


def test_get_all_settings_covers_every_operator_key(live_db):
    everything = get_all_settings(db=live_db)
    assert set(everything) == {k for k in SETTING_DEFS}
    # Secrets come back as values (the admin page masks display), never None:
    assert everything["GOOGLE_API_KEY"] == ""


# ---- override mechanics (what keeps old monkeypatch tests honest) ----------

def test_managed_name_shadowing_restored_by_conftest(live_db):
    set_settings({"SCRAPE_HOUR": 5}, db=live_db)
    descriptor = vars(Config)["SCRAPE_HOUR"]
    Config.SCRAPE_HOUR = 21                        # e.g. a test override
    assert Config.SCRAPE_HOUR == 21
    # Simulate the conftest autouse restore:
    setattr(Config, "SCRAPE_HOUR", descriptor)
    assert Config.SCRAPE_HOUR == 5                 # live lookup again


def test_monkeypatch_on_live_descriptor_roundtrips(live_db, monkeypatch):
    """pytest 9 records the DESCRIPTOR from __dict__ as the old value and
    reinstates it on undo — so monkeypatched reads work during the test
    and the live lookup resumes after."""
    set_settings({"SCRAPE_HOUR": 5}, db=live_db)
    monkeypatch.setattr(Config, "SCRAPE_HOUR", 21, raising=True)
    assert Config.SCRAPE_HOUR == 21


def test_reads_never_create_database(tmp_path, monkeypatch):
    """A config read against a nonexistent database must not create one —
    no test or worker should materialize data/ by accident."""
    probe = tmp_path / "never.db"
    monkeypatch.setattr(Config, "DATABASE_PATH", probe)
    assert get_setting("SCRAPE_HOUR") == 4
    assert not probe.exists()
    assert not (tmp_path / "data").exists()


def test_bootstrap_env_only_for_database_path(monkeypatch, tmp_path):
    """DATABASE_PATH stays environment-driven (bootstrap); managed keys do
    NOT consult the environment at all."""
    monkeypatch.setenv("SCRAPE_HOUR", "17")
    monkeypatch.setattr(Config, "DATABASE_PATH", tmp_path / "boot.db")

    from core.database import Database
    Database().init_database()

    assert Config.SCRAPE_HOUR == 4                 # env ignored for managed keys
    # DATABASE_PATH is deliberately frozen at import — that is exactly what
    # makes it a bootstrap key. Post-import env changes must NOT move it.
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "elsewhere.db"))
    assert Config.DATABASE_PATH != tmp_path / "elsewhere.db"


# ---- hashing ----------------------------------------------------------------

def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("scrypt$")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("correct horse battery stapl", stored)
    assert not verify_password("", stored)


def test_password_hash_unique_per_call():
    assert hash_password("same") != hash_password("same")   # salted


def test_verify_password_fails_closed_on_garbage():
    assert not verify_password("x", "")
    assert not verify_password("", "scrypt$1$1$1$AA==$AA==")
    assert not verify_password("x", "plaintext-not-a-hash")
