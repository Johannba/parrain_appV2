from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def abs_uri(context, path: str) -> str:
    """
    Construit une URL absolue à partir d'un path relatif, en utilisant request si dispo.
    Usage dans template:
      {% abs_uri rw.claim_path as claim_abs %}
    """
    request = context.get("request")
    if not path:
        return ""
    return request.build_absolute_uri(path) if request else path
