"""Structural guard for the one behaviour with real-world consequences:
the export/draft layer must never be able to SEND anything.

If someone adds smtplib (or any mail transport) to core/exports.py, this
fails before a vendor ever receives an accidental email.
"""

import pathlib


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
