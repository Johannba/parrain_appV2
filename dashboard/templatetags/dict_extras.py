# dashboard/templatetags/dict_extras.py
from __future__ import annotations
from django import template

register = template.Library()

@register.filter
def get_normalized_percentages(company, client):
    """
    Retourne un dict {SOUVENT, MOYEN, RARE, TRES_RARE} normalisé à 100.
    - Essaie d’appeler un service si présent (ex: rewards.services.eligibility_percentages),
      sinon fallback à des valeurs par défaut.
    - Toujours “safe” pour le template : renvoie un dict exploitable.
    """
    # ---- tenter un service applicatif si tu en as un ----
    data = None
    try:
        # Optionnel : si tu as un service qui calcule les scores/bruts
        # from rewards.services import eligibility_percentages
        # data = eligibility_percentages(company=company, client=client)
        pass
    except Exception:
        data = None

    keys = ["SOUVENT", "MOYEN", "RARE", "TRES_RARE"]

    # Si pas de data → valeurs par défaut “raisonnables”
    if not isinstance(data, dict):
        return {"SOUVENT": 40, "MOYEN": 30, "RARE": 20, "TRES_RARE": 10}

    # Normalisation
    try:
        raw = {k: float(data.get(k, 0) or 0) for k in keys}
        total = sum(v for v in raw.values() if v > 0)
        if total <= 0:
            return {"SOUVENT": 40, "MOYEN": 30, "RARE": 20, "TRES_RARE": 10}
        pct = {k: int(round(100 * raw[k] / total)) for k in keys}
        # Ajuster l’arrondi pour que la somme fasse bien 100
        diff = 100 - sum(pct.values())
        if diff != 0:
            # ajoute/enlève le diff sur la classe la plus fréquente
            max_key = max(keys, key=lambda k: raw[k])
            pct[max_key] = max(0, pct[max_key] + diff)
        return pct
    except Exception:
        # En cas d’imprévu, rester robuste
        return {"SOUVENT": 40, "MOYEN": 30, "RARE": 20, "TRES_RARE": 10}
