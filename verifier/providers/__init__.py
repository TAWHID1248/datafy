"""Provider factory. Selects the backend from settings.VERIFIER_PROVIDER.

Steps whose task_type starts with ``local:`` never leave the machine; they are
served by the offline providers regardless of VERIFIER_PROVIDER.
"""

from django.conf import settings

from .base import VerificationProvider  # re-export
from .local import LineTypeProvider, is_local_task
from .mock import MockProvider


def get_provider(task_type=None) -> VerificationProvider:
    if task_type and is_local_task(task_type):
        return LineTypeProvider()
    name = getattr(settings, "VERIFIER_PROVIDER", "mock").lower()
    if name == "checknumber":
        from .checknumber import CheckNumberProvider

        return CheckNumberProvider()
    return MockProvider()
