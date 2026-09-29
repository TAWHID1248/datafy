"""Offline line-type provider (no network, no cost).

Classifies E.164 numbers with libphonenumber's numbering-plan metadata:
mobile, landline, VoIP, toll-free, premium-rate, ... For countries whose plan
separates mobile and landline ranges (the UK, most of Europe and Asia) this is
authoritative. North American numbers (US, Canada) do not separate the two, so
they come back as "mobile or landline" and pass both filters; use the paid
Number Carrier lookup when you need a definite answer there.

The task_type selects the filter:

  local:line_type:mobile    keep mobiles (and "mobile or landline")
  local:line_type:landline  keep landlines (and "mobile or landline")
  local:line_type:any       keep everything, just record the type

The step's raw status / export ``detail`` column carries the type name.
"""

from decimal import Decimal

import phonenumbers
from phonenumbers import PhoneNumberType as T

from ..models import Outcome
from .base import (
    ContactStatus,
    FetchResult,
    PollResult,
    SubmitResult,
    VerificationProvider,
)

PREFIX = "local:line_type:"

_LABELS = {
    T.MOBILE: "mobile",
    T.FIXED_LINE: "landline",
    T.FIXED_LINE_OR_MOBILE: "mobile or landline",
    T.VOIP: "voip",
    T.TOLL_FREE: "toll-free",
    T.PREMIUM_RATE: "premium-rate",
    T.SHARED_COST: "shared-cost",
    T.PERSONAL_NUMBER: "personal",
    T.PAGER: "pager",
    T.UAN: "uan",
    T.VOICEMAIL: "voicemail",
}

_PASS = {
    "mobile": {T.MOBILE, T.FIXED_LINE_OR_MOBILE},
    "landline": {T.FIXED_LINE, T.FIXED_LINE_OR_MOBILE},
}


def line_type(value: str):
    """Return (phonenumbers type constant | None, label)."""
    try:
        parsed = phonenumbers.parse(value, None)
    except phonenumbers.NumberParseException:
        return None, "unparseable"
    kind = phonenumbers.number_type(parsed)
    if kind == T.UNKNOWN:
        return None, "unknown"
    return kind, _LABELS.get(kind, "unknown")


def is_local_task(task_type: str) -> bool:
    return (task_type or "").startswith(PREFIX)


class LineTypeProvider(VerificationProvider):
    """Stateless: the "task" completes instantly and fetch recomputes from contacts."""

    name = "line_type"

    def submit(self, contacts, task_type):
        contacts = list(contacts)
        return SubmitResult(
            task_id=task_type, total=len(contacts), estimated_cost=Decimal(0)
        )

    def poll(self, task_id):
        return PollResult(state="done", done=True, result_url=task_id,
                          actual_cost=Decimal(0))

    def fetch(self, poll_result, contacts):
        mode = (poll_result.result_url or "").removeprefix(PREFIX) or "any"
        keep = _PASS.get(mode)
        statuses = []
        for c in contacts:
            kind, label = line_type(c)
            if kind is None:
                outcome = Outcome.UNRESOLVED
            elif keep is None or kind in keep:
                outcome = Outcome.VALID
            else:
                outcome = Outcome.INVALID
            statuses.append(ContactStatus(value=c, outcome=outcome, raw_status=label))
        return FetchResult(statuses=statuses, actual_cost=Decimal(0))
