from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """Dict lookup by variable key: {{ row|get_item:column }}."""
    try:
        return mapping.get(key, "")
    except AttributeError:
        return ""
