"""Contact normalization and eligibility flagging.

Phone numbers use Google's libphonenumber (via the ``phonenumbers`` package):
an existing international ``+`` prefix is respected; a bare national number is
parsed against the job's default region (or a per-row country column). Emails
get light structural validation. Nothing here mutates the original value — the
normalized form is returned separately and stored in its own column.
"""

import re

import phonenumbers

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone(raw, default_region=None, row_region=None):
    """Return (normalized_e164 | "", flag_reason | "").

    flag_reason is empty when the number is usable; otherwise it explains why
    the value was flagged (missing / unparseable / not a valid number).
    """
    if raw is None:
        return "", "missing"
    value = str(raw).strip()
    if not value:
        return "", "missing"

    # Collapse spacing/formatting noise but keep a leading +.
    cleaned = re.sub(r"[^\d+]", "", value)
    if not cleaned:
        return "", "no digits"

    # A country column pointing at non-region data (a phone column, a country
    # name, garbage) must not poison the parse — ignore anything that isn't a
    # known ISO region code and fall back to the job default.
    region = (row_region or "").strip().upper()
    if region not in phonenumbers.SUPPORTED_REGIONS:
        region = None
    region = region or default_region or None
    try:
        # A leading + means it already carries a country code; pass region=None.
        parsed = phonenumbers.parse(
            cleaned, None if cleaned.startswith("+") else region
        )
    except phonenumbers.NumberParseException:
        # Bare number with no region to anchor it -> can't determine country.
        if not cleaned.startswith("+") and not region:
            return "", "no country code"
        return "", "unparseable"

    if not phonenumbers.is_valid_number(parsed):
        return "", "invalid number"
    e164 = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.E164
    )
    return e164, ""


def normalize_email(raw):
    """Return (normalized_email | "", flag_reason | "")."""
    if raw is None:
        return "", "missing"
    value = str(raw).strip().lower()
    if not value:
        return "", "missing"
    if not _EMAIL_RE.match(value):
        return "", "malformed email"
    return value, ""


def normalize(raw, contact_type, default_region=None, row_region=None):
    if contact_type == "email":
        return normalize_email(raw)
    return normalize_phone(raw, default_region=default_region, row_region=row_region)
