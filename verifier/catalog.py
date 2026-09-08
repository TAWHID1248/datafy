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

DEFAULT_CHECKER = "basic"

# service_key -> {
#   label,
#   task_types: {contact_type: provider_task_type_code},   # the basic checker
#   checkers:   {checker_key: {label, price, task_types: {...}}}  # optional extra tiers
# }
#
# Every service implicitly has a "basic" checker built from ``task_types``.
# ``checkers`` lists the higher tiers the provider sells for the same platform
# (e.g. WhatsApp "Number Activity" = ``ws_active``). All tiers return the same
# ``number``/``activated`` core columns, so the result parser is shared; the
# extra columns the richer tiers return are not persisted.
# ``price`` is the provider's list price per 10,000 numbers, for display only.
SERVICES = {
    "whatsapp": {
        "label": "WhatsApp",
        "task_types": {PHONE: "ws"},
        "price": "$0.9",
        "checkers": {
            "activity": {
                "label": "Number Activity",
                "price": "$1.8",
                "task_types": {PHONE: "ws_active"},
            },
            "profile": {
                "label": "Number Profile",
                "price": "$3.8",
                "task_types": {PHONE: "ws_avatar"},
            },
        },
    },
    "telegram": {
        "label": "Telegram",
        "task_types": {PHONE: "tg"},
        "price": "$1.5",
        "checkers": {
            "activity": {
                "label": "Number Activity",
                "price": "$3.5",
                "task_types": {PHONE: "tg_active"},
            },
            "profile": {
                "label": "Number Profile",
                "price": "$4.5",
                "task_types": {PHONE: "tg_avatar"},
            },
        },
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


def checkers_for(service_key, contact_type):
    """Return [(checker_key, label, price, task_type), ...] for a service.

    The basic checker always comes first; richer tiers follow in catalog order.
    Only tiers that support ``contact_type`` are included.
    """
    meta = SERVICES.get(service_key)
    if not meta:
        return []
    out = []
    basic = meta["task_types"].get(contact_type)
    if basic:
        label = "Email Checker" if contact_type == EMAIL else "Number Checker"
        out.append((DEFAULT_CHECKER, label, meta.get("price", ""), basic))
    for key, tier in meta.get("checkers", {}).items():
        task_type = tier["task_types"].get(contact_type)
        if task_type:
            out.append((key, tier["label"], tier.get("price", ""), task_type))
    return out


def services_for(contact_type):
    """Return [(key, label, task_type), ...] supporting the given contact type."""
    out = []
    for key, meta in SERVICES.items():
        task_type = meta["task_types"].get(contact_type)
        if task_type:
            out.append((key, meta["label"], task_type))
    return out


def task_type_for(service_key, contact_type, checker=DEFAULT_CHECKER):
    """Resolve the provider task_type code, or None if the combo is unsupported."""
    for key, _label, _price, task_type in checkers_for(service_key, contact_type):
        if key == (checker or DEFAULT_CHECKER):
            return task_type
    return None


def checker_label_for(service_key, contact_type, checker=DEFAULT_CHECKER):
    for key, label, _price, _tt in checkers_for(service_key, contact_type):
        if key == (checker or DEFAULT_CHECKER):
            return label
    return checker or DEFAULT_CHECKER


def label_for(service_key):
    meta = SERVICES.get(service_key)
    return meta["label"] if meta else service_key
