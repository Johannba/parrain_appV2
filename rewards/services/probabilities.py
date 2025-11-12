# rewards/services/probabilities.py
from __future__ import annotations
from decimal import Decimal, getcontext
import random
from typing import Dict
from django.db.models import Max
from dashboard.models import Referral
from rewards.models import RewardTemplate

NO_HIT = "NO_HIT"

# Précision confortable (plus que suffisante pour 0.00001)
getcontext().prec = 28

# Probabilités BRUTES (avant filtre)
# Elles somment à 100 exactement (80 + 19 + 0.99999 + 0.00001)
PROB_FULL: Dict[str, Decimal] = {
    "SOUVENT":   Decimal("80"),
    "MOYEN":     Decimal("19"),
    "RARE":      Decimal("0.99999"),
    "TRES_RARE": Decimal("0.00001"),
}

ORDER = ("SOUVENT", "MOYEN", "RARE", "TRES_RARE")  # stabilité d’itération

def _eligible_buckets(company, referrer) -> Dict[str, int]:
    """map bucket -> min requis (avec défaut 0) + statut d’éligibilité implicite"""
    req_map = {tpl.bucket: int(tpl.min_referrals_required or 0)
               for tpl in RewardTemplate.objects.filter(company=company)}
    # s'assurer qu’on a des entrées pour tous les buckets
    for b in PROB_FULL.keys():
        req_map.setdefault(b, 0)
    return req_map

def tirer_recompense(company, referrer, *, rng=random) -> str:
    """
    1) On calcule le nombre de parrainages actuels du parrain.
    2) On filtre les buckets dont le min n'est pas atteint.
    3) On re-normalise les probabilités restantes pour sommer à 100.
    4) On tire pondéré sur ces probabilités normalisées.
       S'il ne reste rien: NO_HIT.
    """
    current_refs = Referral.objects.filter(company=company, referrer=referrer).count()
    req_map = _eligible_buckets(company, referrer)

    # --- filtre éligibles ---
    elig = [b for b in PROB_FULL.keys() if current_refs >= req_map[b]]
    if not elig:
        return NO_HIT

    # --- somme des probas restantes ---
    sum_rest = sum(PROB_FULL[b] for b in elig)  # ex. 99 si RARE & TR out
    if sum_rest <= 0:
        return NO_HIT

    # --- re-normalisation pour sommer à 100, EXACTE (Decimal) ---
    # new_p[b] = (PROB_FULL[b] / sum_rest) * 100
    new_p: Dict[str, Decimal] = {b: (PROB_FULL[b] / sum_rest) * Decimal("100") for b in elig}

    # --- tirage pondéré sur new_p (somme ≈ 100 exactement) ---
    x = Decimal(str(rng.random())) * Decimal("100")
    acc = Decimal("0")
    for b in ORDER:
        if b in new_p:
            acc += new_p[b]
            if x < acc:
                return b

    # Fallback théorique (bord de précision)
    return elig[0]
