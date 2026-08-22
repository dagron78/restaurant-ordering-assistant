"""
Security helpers shared across the app.

Kept in core/ (no Streamlit imports) so the logic is unit-testable
without pulling in the UI stack.
"""

import hmac


def password_matches(candidate: str, expected: str) -> bool:
    """Constant-time comparison of an entered and configured password."""
    if not expected:
        return False
    return hmac.compare_digest(
        (candidate or '').encode('utf-8'),
        expected.encode('utf-8'),
    )
