"""Verify the active verification provider is reachable and working.

Examples:
    python manage.py provider_check
    python manage.py provider_check --number +14155552671 --task-type whatsapp

Without --number it only checks connectivity/balance. With --number it submits
a real one-item task, polls to completion, and prints the raw provider status —
use this to confirm the `activated` label mapping against your live account.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from verifier.providers import get_provider


class Command(BaseCommand):
    help = "Check the verification provider connection (and optionally one number)."

    def add_arguments(self, parser):
        parser.add_argument("--number", help="A single contact to test end-to-end.")
        parser.add_argument("--task-type", default="whatsapp",
                            help="Provider task_type for the test (default: whatsapp).")

    def handle(self, *args, **opts):
        name = getattr(settings, "VERIFIER_PROVIDER", "mock")
        self.stdout.write(f"Active provider: {self.style.SQL_KEYWORD(name)}")
        if name == "mock":
            self.stdout.write(self.style.WARNING(
                "Provider is 'mock'. Set VERIFIER_PROVIDER=checknumber and "
                "CHECKNUMBER_API_KEY (e.g. in .env) to use the live API."
            ))

        try:
            provider = get_provider()
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f"Could not initialize provider: {exc}"))
            return

        balance = provider.balance()
        self.stdout.write(f"Balance: {balance if balance is not None else 'unknown'}")

        number = opts.get("number")
        if not number:
            self.stdout.write(self.style.SUCCESS("Connectivity OK."))
            return

        task_type = opts["task_type"]
        self.stdout.write(f"Submitting test: {number} -> task_type={task_type} …")
        try:
            sub = provider.submit([number], task_type)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(str(exc)))
            self.stdout.write(
                "Note: the live provider enforces a per-service minimum batch "
                "size (e.g. 500 valid numbers for WhatsApp), so a single-number "
                "test cannot run. Connectivity above still confirms the key."
            )
            return
        self.stdout.write(f"  task_id={sub.task_id} estimated_cost={sub.estimated_cost}")

        import time

        for _ in range(60):
            poll = provider.poll(sub.task_id)
            if poll.failed:
                self.stderr.write(self.style.ERROR(f"Task failed: {poll.message}"))
                return
            if poll.done:
                break
            self.stdout.write(f"  … {poll.state}")
            time.sleep(3)
        else:
            self.stderr.write(self.style.ERROR("Timed out waiting for results."))
            return

        fetch = provider.fetch(poll, [number])
        for st in fetch.statuses:
            self.stdout.write(
                f"  result: {st.value} -> outcome={self.style.SQL_KEYWORD(st.outcome)} "
                f"(raw provider label: '{st.raw_status}')"
            )
        self.stdout.write(self.style.SUCCESS(
            "Done. Confirm the outcome mapping matches your expectation; "
            "adjust _map_status in verifier/providers/checknumber.py if needed."
        ))
