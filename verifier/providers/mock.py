"""Offline mock provider.

Deterministic (no randomness, no network, no cost) so the whole pipeline runs
locally with no API key. The "verification" is a stable hash of the contact
value: roughly 55% valid, 30% invalid, 15% unresolved — enough of a spread to
exercise every downstream bucket and the multi-step filtering rule.

Completion is instant here; the worker still treats it as an async task so the
code path is identical to the live provider.
"""

import hashlib
from decimal import Decimal

from ..models import Outcome
from .base import (
    ContactStatus,
    FetchResult,
    PollResult,
    SubmitResult,
    VerificationProvider,
)

# In-process store of submitted batches, keyed by synthetic task id.
_TASKS: dict[str, dict] = {}


def _bucket(value: str) -> str:
    h = int(hashlib.sha256(value.encode("utf-8")).hexdigest(), 16) % 100
    if h < 55:
        return Outcome.VALID
    if h < 85:
        return Outcome.INVALID
    return Outcome.UNRESOLVED


class MockProvider(VerificationProvider):
    name = "mock"

    def submit(self, contacts, task_type):
        contacts = list(contacts)
        task_id = "mock-" + hashlib.sha1(
            (task_type + "|" + "|".join(contacts)).encode("utf-8")
        ).hexdigest()[:16]
        _TASKS[task_id] = {"contacts": contacts, "task_type": task_type}
        return SubmitResult(
            task_id=task_id,
            total=len(contacts),
            estimated_cost=Decimal(len(contacts)) * Decimal("0.0001"),
        )

    def poll(self, task_id):
        task = _TASKS.get(task_id)
        total = len(task["contacts"]) if task else 0
        return PollResult(
            state="done",
            done=True,
            checked=total,
            result_url=f"mock://{task_id}",
            actual_cost=Decimal(total) * Decimal("0.0001"),
        )

    def fetch(self, poll_result, contacts):
        statuses = [
            ContactStatus(value=c, outcome=_bucket(c), raw_status=_bucket(c))
            for c in contacts
        ]
        return FetchResult(statuses=statuses, actual_cost=poll_result.actual_cost)

    def balance(self):
        return Decimal("999999")
