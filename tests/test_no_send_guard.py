"""Structural guard for the one behaviour with real-world consequences:
the export/draft layer must never be able to SEND anything.

If someone adds smtplib (or any mail transport) to core/exports.py, this
fails before a vendor ever receives an accidental email.
"""

import pathlib

APP = pathlib.Path(__file__).parent.parent / "app"


def _exports_source():
    return (pathlib.Path(__file__).parent.parent /
            "core" / "exports.py").read_text()


def test_exports_never_imports_a_mail_transport():
    src = _exports_source()
    for banned in ("smtplib", "sendmail", "SMTP(", "aiosmtplib"):
        assert banned not in src, f"exports must never send: found {banned}"


def test_no_mail_transport_dependency_is_available_to_exports():
    reqs = (pathlib.Path(__file__).parent.parent /
            "requirements.txt").read_text().lower()
    assert "smtplib" not in reqs          # stdlib anyway; belt for future edits
    for line in reqs.splitlines():
        assert not line.strip().startswith(("smtp", "aiosmtplib")), line


class TestUnconfiguredFailsClosedIntoSetup:
    """Phase A (issue #50) supersedes issue #37's open-access-with-warning:
    an app with no admin password now routes to FIRST-RUN SETUP instead of
    running open. This test runs in the DEFAULT pytest invocation."""

    def test_open_access_warning_is_gone(self):
        gate = (APP / "components" / "auth_gate.py").read_text()
        assert "No APP_PASSWORD is set" not in gate, (
            "open-access warning path still present — Phase A replaced it "
            "with mandatory first-run setup")

    def test_unconfigured_routes_to_first_run_before_any_marker(self):
        gate = (APP / "components" / "auth_gate.py").read_text()
        setup_pos = gate.index("render_setup(db=db)")
        marker_pos = gate.index("st.markdown('<div data-preauth")
        # The first-run branch must precede the gated-mode marker emission:
        # an unconfigured app must never fall through to normal sign-in.
        assert setup_pos < marker_pos

    def test_first_run_sets_passwords_through_the_store(self):
        fr = (APP / "components" / "first_run.py").read_text()
        assert "auth.set_password(\"admin\"" in fr
        assert "auth.set_password(\"app\"" in fr
