# dashboard/templatetags/dict_extras.py
from django import template
register = template.Library()

@register.filter(name="get_item")
def get_item(mapping, key):
    if mapping is None:
        return ""
    # dict-like .get
    try:
        return mapping.get(key, "")
    except AttributeError:
        pass
    # [] fallback
    try:
        return mapping[key]
    except Exception:
        return ""

@register.filter(name="index")
def index(seq, i):
    try:
        return seq[int(i)]
    except Exception:
        return ""

@register.filter(name="attr")
def attr(obj, name):
    return getattr(obj, str(name), "")
