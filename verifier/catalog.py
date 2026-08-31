"""Verification service catalog.

Single source of truth for which services can be checked, which contact types
each supports, and the checknumber.ai ``task_type`` code used per combination.

The provider distinguishes contact type by a code suffix: ``amazon`` checks a
phone number, ``amazon_email`` checks an email address. Not every platform
exposes both variants, so the UI must render only the combinations listed here.

IMPORTANT: the ``task_type`` strings below follow checknumber.ai's documented
naming pattern, but the exact per-service availability of an ``_email`` variant
should be confirmed against your account's live capability list. Because every
task_type is centralised here, correcting one is a one-line change and needs no
edits elsewhere in the codebase.
"""

# Contact type constants.
PHONE = "phone"
EMAIL = "email"

# service_key -> {label, task_types: {contact_type: provider_task_type_code}}
SERVICES = {
    "whatsapp": {
        "label": "WhatsApp",
        "task_types": {PHONE: "ws"},
    },
    "telegram": {
        "label": "Telegram",
        "task_types": {PHONE: "tg"},
    },
    "amazon": {
        "label": "Amazon",
        "task_types": {PHONE: "amazon", EMAIL: "amazon_email"},
    },
    "apple": {
        "label": "Apple ID",
        "task_types": {PHONE: "apple", EMAIL: "apple_email"},
    },
    "facebook": {
        "label": "Facebook",
        "task_types": {PHONE: "facebook", EMAIL: "facebook_email"},
    },
    "instagram": {
        "label": "Instagram",
        "task_types": {PHONE: "instagram", EMAIL: "instagram_email"},
    },
    "spotify": {
        "label": "Spotify",
        "task_types": {EMAIL: "spotify_email"},
    },
    "airbnb": {
        "label": "Airbnb",
        "task_types": {PHONE: "airbnb"},
    },
}


def services_for(contact_type):
    """Return [(key, label, task_type), ...] supporting the given contact type."""
    out = []
    for key, meta in SERVICES.items():
        task_type = meta["task_types"].get(contact_type)
        if task_type:
            out.append((key, meta["label"], task_type))
    return out


def task_type_for(service_key, contact_type):
    """Resolve the provider task_type code, or None if the combo is unsupported."""
    meta = SERVICES.get(service_key)
    if not meta:
        return None
    return meta["task_types"].get(contact_type)


def label_for(service_key):
    meta = SERVICES.get(service_key)
    return meta["label"] if meta else service_key
