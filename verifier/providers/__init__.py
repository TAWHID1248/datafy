"""Provider factory. Selects the backend from settings.VERIFIER_PROVIDER."""

from django.conf import settings

from .base import VerificationProvider  # re-export
from .mock import MockProvider


def get_provider() -> VerificationProvider:
    name = getattr(settings, "VERIFIER_PROVIDER", "mock").lower()
    if name == "checknumber":
        from .checknumber import CheckNumberProvider

        return CheckNumberProvider()
    return MockProvider()
