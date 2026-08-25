"""Open every page against the mock restaurant and confirm it renders.

This exists because of a real failure on this project: a front-end review was
assembled from source reading and old screenshots, and reported an app that was
"refined and easy to use" while the running app dead-ended on a missing API key.
The fixture is worthless if the pages it feeds throw.

Marked slow_ui — it boots six Streamlit pages. CI runs that job explicitly.
"""
import pathlib
import subprocess
import sys

import pytest
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from core import auth  # noqa: E402
from core.config import Config  # noqa: E402
from core.database import Database  # noqa: E402

REPO = pathlib.Path(__file__).parent.parent
VIEWS = REPO / "app" / "views"
PAGES = sorted(p.name for p in VIEWS.glob("*.py"))

pytestmark = pytest.mark.slow_ui


@pytest.fixture(scope="module")
def mock_db(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("walk") / "mock.db"
    env = {"PATH": "/usr/bin:/bin", "DATABASE_PATH": str(db_path),
           "HOME": str(tmp_path_factory.mktemp("home"))}
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "seed_mock_restaurant.py"),
         "--reset"], capture_output=True, text=True, env=env, cwd=str(REPO))
    assert proc.returncode == 0, proc.stderr
    db = Database(db_path=db_path)
    auth.set_password("app", "app-secret", db=db)
    auth.set_password("admin", "admin-secret", db=db)
    return db


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_against_the_mock_restaurant(page, mock_db, monkeypatch):
    """No page may raise, and none may dead-end on a missing API key —
    the mock restaurant is explicitly a keyless demo."""
    monkeypatch.setattr(Config, "DATABASE_PATH", mock_db.db_path, raising=True)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    at = AppTest.from_file(str(VIEWS / page))
    at.session_state["role"] = "admin"
    at.run(timeout=60)

    assert not at.exception, (
        f"{page} raised: "
        f"{[str(getattr(e, 'value', e)) for e in at.exception]}")


def test_the_demo_shows_its_data_not_an_empty_state(mock_db, monkeypatch):
    """Rendering without raising is not the same as showing anything.
    The Order Guide must actually name items from the fixture."""
    monkeypatch.setattr(Config, "DATABASE_PATH", mock_db.db_path, raising=True)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    at = AppTest.from_file(str(VIEWS / "1_📋_Order_Guide.py"))
    at.session_state["role"] = "admin"
    at.run(timeout=60)
    assert not at.exception

    text = "\n".join(
        str(getattr(e, "value", ""))
        for attr in ("markdown", "code", "caption", "title", "subheader",
                     "info", "warning", "success", "text", "dataframe",
                     "table", "metric")
        for e in getattr(at, attr, []))
    assert "Chicken Breast" in text or "Roma Tomatoes" in text, (
        "Order Guide rendered but named no fixture item:\n" + text[:1200])
