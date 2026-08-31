"""Provider interface and shared result types.

Any verification backend implements ``VerificationProvider``. The orchestrator
only ever talks to this interface, so swapping mock <-> checknumber.ai (or adding
another provider later) never touches job logic.

The provider is asynchronous and file-based: you *submit* a batch and get a
task id, later *poll* that id, and once it is done *fetch* the per-contact
statuses. Each provider maps its own raw status labels onto the shared
three-bucket ``Outcome`` so the rest of the system stays provider-agnostic.
"""

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class SubmitResult:
    task_id: str
    total: int = 0
    estimated_cost: Decimal | None = None


@dataclass
class PollResult:
    # normalized lifecycle: "pending" | "processing" | "done" | "failed"
    state: str
    done: bool = False
    failed: bool = False
    checked: int = 0
    result_url: str = ""
    actual_cost: Decimal | None = None
    message: str = ""


@dataclass
class ContactStatus:
    """One provider result row, already mapped to a normalized outcome."""

    value: str          # the phone/email the provider echoed back
    outcome: str        # verifier.models.Outcome value
    raw_status: str = ""


@dataclass
class FetchResult:
    statuses: list[ContactStatus] = field(default_factory=list)
    actual_cost: Decimal | None = None


class VerificationProvider:
    name = "base"

    def submit(self, contacts, task_type):
        """Submit a batch of contact strings. Returns SubmitResult."""
        raise NotImplementedError

    def poll(self, task_id):
        """Check task lifecycle. Returns PollResult."""
        raise NotImplementedError

    def fetch(self, poll_result, contacts):
        """Retrieve per-contact statuses once the task is done. FetchResult."""
        raise NotImplementedError

    def balance(self):
        """Return remaining credit as Decimal, or None if unknown."""
        return None
