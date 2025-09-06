# dashboard/templatetags/proba_extras.py
from django import template

register = template.Library()

def _compute_percentages(company, client):
    """
    TODO: remplace par ta vraie logique d'éligibilité.
    Ici on retourne des valeurs par défaut stables.
    Si tu as une méthode côté modèle (ex: company.get_normalized_percentages(client)),
    on l'appelle si elle existe.
    """
    # Si tu as une méthode métier, on la privilégie
    maybe = getattr(company, "get_normalized_percentages", None)
    if callable(maybe):
        try:
            data = maybe(client)
            if isinstance(data, dict) and {"SOUVENT","MOYEN","RARE","TRES_RARE"} <= set(data.keys()):
                return data
        except Exception:
            pass

    # Valeurs par défaut (remplace si besoin)
    return {
        "SOUVENT": 25,
        "MOYEN": 35,
        "RARE": 25,
        "TRES_RARE": 15,
    }

@register.filter(name="get_normalized_percentages")
def get_normalized_percentages(company, client):
    """
    Usage dans la template :
      {% with P=company|get_normalized_percentages:client %} ... {% endwith %}
    """
    if company is None or client is None:
        return {}
    return _compute_percentages(company, client)
