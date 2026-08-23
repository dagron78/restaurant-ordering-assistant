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


class TestOpenAccessNavigation:
    """Issue #37: with no APP_PASSWORD, the data-preauth marker must NOT
    be emitted — it hides the sidebar, making the app unusable in its
    default state. This test runs in the DEFAULT pytest invocation."""

    def test_marker_not_emitted_when_password_unset(self):
        gate = (APP / "components" / "auth_gate.py").read_text()
        # Search for the actual emission, not docstring/comment mentions
        marker_pos = gate.index("st.markdown('<div data-preauth")
        warning_pos = gate.index("No APP_PASSWORD is set")
        return_pos = gate.index("return", warning_pos)
        # Marker must come AFTER the no-password early return
        assert marker_pos > return_pos, (
            "data-preauth marker emitted before the no-password check — "
            "open-access users lose their navigation (issue #37 regression)")
