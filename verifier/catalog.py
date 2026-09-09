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

# Dropdown groups, in display order.
GROUPS = [
    ("social", "Messaging & social"),
    ("phone", "Phone number checks"),
    ("commerce", "Commerce & services"),
    ("exchange", "Crypto exchanges"),
    ("email", "Email accounts"),
]

# service_key -> {
#   label,
#   group:       one of GROUPS,
#   task_types:  {contact_type: provider_task_type_code},   # the basic checker
#   price:       "$x" or {contact_type: "$x"}   # list price per 10,000, display only
#   basic_label: optional label for the basic checker (default "Number Checker"
#                / "Email Checker")
#   checkers:    {checker_key: {label, price, task_types: {...}}}  # optional tiers
# }
#
# Every service implicitly has a "basic" checker built from ``task_types``.
# ``checkers`` lists the higher tiers the provider sells for the same platform
# (e.g. WhatsApp "Number Activity" = ``ws_active``). All tiers return the same
# ``number``/``activated`` core columns, so the result parser is shared; the
# extra columns the richer tiers return are not persisted.
#
# task_type codes and prices come from docs.checknumber.ai and the
# checknumber.ai pricing page (checked 2026-09-09). Note the provider's odd
# capitalisation on a few codes (``Binance``, ``Kucoin``, ``coinW``) - they are
# sent verbatim.
#
# Deliberately NOT listed: Telegram username checkers (``tg_username``,
# ``tg_username_activity``) because they take usernames, not phones or emails;
# carrier lookups (``globalCarrier``, ``us_carrier_premium``) because they
# return carrier data rather than a yes/no ``activated`` verdict; and the
# "E-commerce Activity" checker, which has no documented task_type.
SERVICES = {
    # --- Messaging & social ------------------------------------------------
    "whatsapp": {
        "label": "WhatsApp", "group": "social",
        "task_types": {PHONE: "ws"}, "price": "$0.9",
        "checkers": {
            "advanced": {"label": "Advanced Checker", "price": "$1",
                         "task_types": {PHONE: "ws_advanced"}},
            "activity": {"label": "Number Activity", "price": "$1.8",
                         "task_types": {PHONE: "ws_active"}},
            "profile": {"label": "Number Profile", "price": "$3.8",
                        "task_types": {PHONE: "ws_avatar"}},
        },
    },
    "telegram": {
        "label": "Telegram", "group": "social",
        "task_types": {PHONE: "tg"}, "price": "$1.5",
        "checkers": {
            "activity": {"label": "Number Activity", "price": "$3.5",
                         "task_types": {PHONE: "tg_active"}},
            "profile": {"label": "Number Profile", "price": "$4.5",
                        "task_types": {PHONE: "tg_avatar"}},
        },
    },
    "viber": {
        "label": "Viber", "group": "social",
        "task_types": {PHONE: "viber"}, "price": "$0.5",
        "checkers": {
            "activity": {"label": "Number Activity", "price": "$5",
                         "task_types": {PHONE: "viber_active"}},
            "profile": {"label": "Number Profile", "price": "$15",
                        "task_types": {PHONE: "viber_senior"}},
        },
    },
    "imessage": {"label": "iMessage", "group": "social",
                 "task_types": {PHONE: "imessage"}, "price": "$2"},
    "rcs": {"label": "RCS", "group": "social",
            "task_types": {PHONE: "rcs"}, "price": "$1.5"},
    "signal": {"label": "Signal", "group": "social",
               "task_types": {PHONE: "signal"}, "price": "$1.5"},
    "facebook": {
        "label": "Facebook", "group": "social",
        "task_types": {PHONE: "facebook", EMAIL: "facebook_email"},
        "price": {PHONE: "$0.3", EMAIL: "$0.3"},
    },
    "messenger": {"label": "Messenger", "group": "social",
                  "task_types": {PHONE: "messenger"}, "price": "$2.8"},
    "instagram": {
        "label": "Instagram", "group": "social",
        "task_types": {PHONE: "instagram", EMAIL: "instagram_email"},
        "price": {PHONE: "$0.3", EMAIL: "$0.3"},
    },
    "threads": {"label": "Threads", "group": "social",
                "task_types": {PHONE: "threads"}, "price": "$0.8"},
    "tiktok": {"label": "TikTok", "group": "social",
               "task_types": {PHONE: "tiktok"}, "price": "$9"},
    "snapchat": {"label": "Snapchat", "group": "social",
                 "task_types": {PHONE: "snapchat"}, "price": "$15"},
    "linkedin": {
        "label": "LinkedIn", "group": "social",
        "task_types": {PHONE: "linkedin_phone", EMAIL: "linkedin"},
        "price": {PHONE: "$4", EMAIL: "$0.3"},
        "checkers": {
            "profile": {"label": "Email Profile", "price": "$3",
                        "task_types": {EMAIL: "linkedin_profile"}},
        },
    },
    "vk": {"label": "VK", "group": "social",
           "task_types": {PHONE: "vk"}, "price": "$5"},
    "max": {
        "label": "MAX", "group": "social",
        "task_types": {PHONE: "max"}, "price": "$10",
        "checkers": {
            "profile": {"label": "Number Profile", "price": "$20",
                        "task_types": {PHONE: "max_full"}},
        },
    },
    "line": {
        "label": "Line", "group": "social",
        "task_types": {PHONE: "line"}, "price": "$5",
        "checkers": {
            "profile": {"label": "Number Profile", "price": "$15",
                        "task_types": {PHONE: "line_senior"}},
        },
    },
    "zalo": {
        "label": "Zalo", "group": "social",
        "task_types": {PHONE: "zalo"}, "price": "$2",
        "checkers": {
            "activity": {"label": "Number Activity", "price": "$8",
                         "task_types": {PHONE: "zalo_active"}},
            "profile": {"label": "Number Profile", "price": "$10",
                        "task_types": {PHONE: "zalo_gender"}},
        },
    },
    "botim": {
        "label": "Botim", "group": "social", "basic_label": "Account Checker",
        "task_types": {PHONE: "botim"}, "price": "$5",
        "checkers": {
            "profile": {"label": "Number Profile", "price": "$7",
                        "task_types": {PHONE: "botim_gender"}},
        },
    },
    "band": {"label": "Band", "group": "social",
             "task_types": {PHONE: "band"}, "price": "$1"},
    "goto": {"label": "GoTo", "group": "social",
             "task_types": {PHONE: "goto"}, "price": "$7"},
    "sideline": {"label": "Sideline", "group": "social",
                 "task_types": {PHONE: "sideline"}, "price": "$1.5"},
    "rusdate": {"label": "RusDate", "group": "social", "basic_label": "Account Checker",
                "task_types": {EMAIL: "rusdate_email"}, "price": "$2"},
    "bongacams": {"label": "BongaCams", "group": "social", "basic_label": "Account Checker",
                  "task_types": {EMAIL: "bongacams"}, "price": "$2"},
    "pornhub": {"label": "Pornhub", "group": "social",
                "task_types": {EMAIL: "pornhub"}, "price": "$7"},

    # --- Phone number checks ----------------------------------------------
    "number": {
        "label": "Number Checker", "group": "phone",
        "basic_label": "Number Validation",
        "task_types": {PHONE: "phoneCheck"}, "price": "$1.5",
        "checkers": {
            "activity": {"label": "Number Activity", "price": "$4.5",
                         "task_types": {PHONE: "active_check"}},
            "high_value": {"label": "High-Value Number", "price": "$5.5",
                           "task_types": {PHONE: "high_value_users"}},
        },
    },

    # --- Commerce & services ----------------------------------------------
    "amazon": {
        "label": "Amazon", "group": "commerce",
        "task_types": {PHONE: "amazon", EMAIL: "amazon_email"},
        "price": {PHONE: "$2", EMAIL: "$2"},
    },
    "apple": {
        "label": "Apple ID", "group": "commerce",
        "task_types": {PHONE: "apple", EMAIL: "apple_email"},
        "price": {PHONE: "$1.5", EMAIL: "$2"},
    },
    "microsoft": {"label": "Microsoft", "group": "commerce",
                  "task_types": {PHONE: "microsoft"}, "price": "$2"},
    "netflix": {
        "label": "Netflix", "group": "commerce",
        "task_types": {PHONE: "netflix", EMAIL: "netflix_email"},
        "price": {PHONE: "$7", EMAIL: "$7"},
    },
    "spotify": {"label": "Spotify", "group": "commerce",
                "task_types": {EMAIL: "spotify_email"}, "price": "$1"},
    "airbnb": {"label": "Airbnb", "group": "commerce",
               "task_types": {PHONE: "airbnb"}, "price": "$2"},
    "temu": {"label": "Temu", "group": "commerce",
             "task_types": {PHONE: "temu"}, "price": "$2"},
    "dhl": {"label": "DHL", "group": "commerce",
            "task_types": {PHONE: "dhl"}, "price": "$1.5"},
    "wheely": {"label": "Wheely", "group": "commerce", "basic_label": "Account Checker",
               "task_types": {PHONE: "wheely"}, "price": "$5"},
    "rabota": {"label": "Rabota.ru", "group": "commerce", "basic_label": "Account Checker",
               "task_types": {PHONE: "rabota_phone"}, "price": "$2"},

    # --- Crypto exchanges --------------------------------------------------
    "binance": {"label": "Binance", "group": "exchange",
                "task_types": {PHONE: "Binance"}, "price": "$6.5"},
    "kucoin": {
        "label": "KuCoin", "group": "exchange",
        "task_types": {PHONE: "Kucoin", EMAIL: "kucoin_email"},
        "price": {PHONE: "$7", EMAIL: "$7"},
    },
    "htx": {
        "label": "Htx", "group": "exchange",
        "task_types": {PHONE: "htx", EMAIL: "htx_email"},
        "price": {PHONE: "$3.5", EMAIL: "$7"},
    },
    "coinw": {
        "label": "CoinW", "group": "exchange",
        "task_types": {PHONE: "coinW", EMAIL: "coinw_email"},
        "price": {PHONE: "$2", EMAIL: "$7"},
    },
    "okx": {"label": "OKX", "group": "exchange", "basic_label": "Account Checker",
            "task_types": {PHONE: "okx"}, "price": "$15"},
    "cryptocom": {"label": "Crypto.com", "group": "exchange",
                  "task_types": {EMAIL: "crypto_email"}, "price": "$15"},

    # --- Email accounts ----------------------------------------------------
    "gmail": {
        "label": "Gmail", "group": "email", "basic_label": "Account Checker",
        "task_types": {EMAIL: "gmail_register"}, "price": "$4.5",
        "checkers": {
            "avatar": {"label": "Avatar Checker", "price": "$5",
                       "task_types": {EMAIL: "gmail_avatar"}},
        },
    },
    "yandex": {
        "label": "Yandex", "group": "email", "basic_label": "Account Checker",
        "task_types": {EMAIL: "yandex_register"}, "price": "$3",
        "checkers": {
            "avatar": {"label": "Avatar Checker", "price": "$3.5",
                       "task_types": {EMAIL: "yandex_avatar"}},
        },
    },
    "mailru": {
        "label": "Mail.ru", "group": "email", "basic_label": "Account Checker",
        "task_types": {EMAIL: "mailru_register"}, "price": "$0.5",
        "checkers": {
            "avatar": {"label": "Avatar Checker", "price": "$1",
                       "task_types": {EMAIL: "mailru_avatar"}},
        },
    },
    "outlook": {"label": "Outlook", "group": "email", "basic_label": "Account Checker",
                "task_types": {EMAIL: "outlook"}, "price": "$2"},
    "yahoo": {"label": "Yahoo", "group": "email", "basic_label": "Yahoo Checker",
              "task_types": {EMAIL: "yahoo"}, "price": "$2"},
    "email_validation": {"label": "Email Validation", "group": "email",
                         "basic_label": "Account Checker",
                         "task_types": {EMAIL: "email_check"}, "price": "$7"},
}


def _price(meta, contact_type):
    """Resolve a ``price`` value that may be a string or per-contact-type dict."""
    price = meta.get("price", "")
    if isinstance(price, dict):
        return price.get(contact_type, "")
    return price


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
        label = meta.get("basic_label") or (
            "Email Checker" if contact_type == EMAIL else "Number Checker"
        )
        out.append((DEFAULT_CHECKER, label, _price(meta, contact_type), basic))
    for key, tier in meta.get("checkers", {}).items():
        task_type = tier["task_types"].get(contact_type)
        if task_type:
            out.append((key, tier["label"], _price(tier, contact_type), task_type))
    return out


def services_grouped(contact_type):
    """Return [(group_label, [(key, label, task_type), ...]), ...] in GROUPS order.

    Groups with no service supporting ``contact_type`` are omitted.
    """
    by_group = {g: [] for g, _ in GROUPS}
    for key, label, task_type in services_for(contact_type):
        by_group[SERVICES[key]["group"]].append((key, label, task_type))
    return [(glabel, by_group[g]) for g, glabel in GROUPS if by_group[g]]


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
