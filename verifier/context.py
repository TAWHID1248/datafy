from django.conf import settings


def globals(request):
    """Values available to every template."""
    return {
        "provider_live": getattr(settings, "VERIFIER_PROVIDER", "mock") != "mock",
    }
