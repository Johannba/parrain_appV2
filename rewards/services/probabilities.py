# rewards/services/probabilities.py
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, getcontext
from typing import Dict, List, Tuple, Set

from django.db import transaction
from django.shortcuts import render

from accounts.models import Company
from rewards.models import ProbabilityWheel, RewardTemplate
from dashboard.models import Referral

# Compatibilité avec les anciens helpers/tests
from rewards.probabilities import (
    WheelSpec as _LegacyWheelSpec,
    ensure_wheel as _legacy_ensure_wheel,
    draw as _legacy_draw,
)


# Expose les symboles historiques
WheelSpec = _LegacyWheelSpec
ensure_wheel = _legacy_ensure_wheel
draw = _legacy_draw

# ------------------ Définition des deux roues “exactes” ------------------
BASE_KEY = "base_100"           # 1000 cases = 980/19/1
VERY_RARE_KEY = "very_rare_10000"  # 100_000 cases = 1 TRES_RARE

SOUVENT = "SOUVENT"
MOYEN = "MOYEN"
RARE = "RARE"
TRES_RARE = "TRES_RARE"
NO_HIT = "NO_HIT"

BASE_COUNTS = {SOUVENT: 980, MOYEN: 19, RARE: 1}
BASE_SIZE = sum(BASE_COUNTS.values())  # 1000

VR_COUNTS = {NO_HIT: 100_000 - 1, TRES_RARE: 1}
VR_SIZE = sum(VR_COUNTS.values())  # 100_000

getcontext().prec = 28  # précision si on affiche des pourcentages

def _build_base_pool() -> List[str]:
    pool: List[str] = []
    for token, n in BASE_COUNTS.items():
        pool.extend([token] * n)
    return pool

def _build_very_rare_pool() -> List[str]:
    pool: List[str] = []
    for token, n in VR_COUNTS.items():
        pool.extend([token] * n)
    return pool

@transaction.atomic
def ensure_wheels(company: Company) -> Tuple[ProbabilityWheel, ProbabilityWheel]:
    """
    Crée (ou met à niveau) les deux roues exactes pour l’entreprise.
    """
    base, _ = ProbabilityWheel.objects.get_or_create(
        company=company,
        key=BASE_KEY,
        defaults={"pool": _build_base_pool(), "size": BASE_SIZE, "idx": 0},
    )
    very_rare, _ = ProbabilityWheel.objects.get_or_create(
        company=company,
        key=VERY_RARE_KEY,
        defaults={"pool": _build_very_rare_pool(), "size": VR_SIZE, "idx": 0},
    )

    if base.size != BASE_SIZE:
        base.pool, base.size, base.idx = _build_base_pool(), BASE_SIZE, 0
        base.save(update_fields=["pool", "size", "idx"])

    if very_rare.size != VR_SIZE:
        very_rare.pool, very_rare.size, very_rare.idx = _build_very_rare_pool(), VR_SIZE, 0
        very_rare.save(update_fields=["pool", "size", "idx"])

    return base, very_rare

def rebuild_wheel(company: Company, key: str) -> None:
    if key == BASE_KEY:
        pool, size = _build_base_pool(), BASE_SIZE
    elif key == VERY_RARE_KEY:
        pool, size = _build_very_rare_pool(), VR_SIZE
    else:
        raise ValueError(f"Clé de roue inconnue: {key}")

    ProbabilityWheel.objects.update_or_create(
        company=company, key=key,
        defaults={"pool": pool, "size": size, "idx": 0}
    )

def reset_wheel(company: Company, key: str) -> None:
    wheel = ProbabilityWheel.objects.get(company=company, key=key)
    wheel.idx = 0
    wheel.save(update_fields=["idx"])

def _eligible_buckets_for(company: Company, client) -> Dict[str, bool]:
    # 1) Compter les parrainages du client (en tant que parrain)
    referrals_count = Referral.objects.filter(company=company, referrer=client).count()

    # 2) Charger les templates (avec min requis)
    tpls = {
        t.bucket: t
        for t in RewardTemplate.objects.filter(company=company).only("bucket", "min_referrals_required")
    }

    def is_ok(bucket: str) -> bool:
        tpl = tpls.get(bucket)
        if not tpl:
            return False
        min_required = int(tpl.min_referrals_required or 0)
        return referrals_count >= min_required

    # 3) IMPORTANT : appliquer la règle à TOUS les buckets
    return {
        SOUVENT:   is_ok(SOUVENT),
        MOYEN:     is_ok(MOYEN),
        RARE:      is_ok(RARE),
        TRES_RARE: is_ok(TRES_RARE),
    }

def _consume_one_eligible(wheel: ProbabilityWheel, allowed: Set[str]) -> str:
    """
    Consomme la roue en sautant les cases non autorisées.
    Normalisation implicite et déterminisme conservé.
    """
    if wheel.size == 0:
        raise ValueError("Roue vide")

    for _ in range(wheel.size):
        val = wheel.pool[wheel.idx]
        wheel.idx = (wheel.idx + 1) % wheel.size
        if val in allowed:
            wheel.save(update_fields=["idx"])
            return val

    # Rien d'autorisé trouvé sur un cycle complet
    wheel.save(update_fields=["idx"])
    return NO_HIT
def tirer_recompense(company: Company, client) -> str:
    elig = _eligible_buckets_for(company, client)
    base, very_rare = ensure_wheels(company)

    allowed_vr = {NO_HIT}
    if elig.get(TRES_RARE, False):
        allowed_vr.add(TRES_RARE)

    vr = _consume_one_eligible(very_rare, allowed_vr)
    if vr == TRES_RARE:
        return TRES_RARE

    allowed_base: Set[str] = set()
    if elig.get(SOUVENT, False): allowed_base.add(SOUVENT)
    if elig.get(MOYEN,   False): allowed_base.add(MOYEN)
    if elig.get(RARE,    False): allowed_base.add(RARE)

    # ⬇️ Nouveau : si aucune catégorie base n'est éligible, on ne force pas SOUVENT
    if not allowed_base:
        return NO_HIT

    return _consume_one_eligible(base, allowed_base)


# Ajoute ceci dans rewards/services/probabilities.py

from decimal import Decimal, getcontext  # tu l'as déjà en haut du fichier
getcontext().prec = 28  # pour éviter les erreurs d'arrondi

def get_normalized_percentages(company: Company, client) -> Dict[str, Decimal]:
    """
    Calcule les pourcentages affichés côté UI en partant des probabilités
    “canoniques” demandées (avant seuils) puis en RENORMALISANT pour que
    la somme fasse exactement 100, en tenant compte de l'éligibilité.
      - SOUVENT   = 80 / 100
      - MOYEN     = 19 / 100
      - RARE      = 0.99999 / 100
      - TRES_RARE = 1 / 100000
    """
    elig = _eligible_buckets_for(company, client)

    # Poids de base (sur [0..1])
    p_base = {
        SOUVENT: Decimal("80") / Decimal("100"),        # 0.80
        MOYEN:   Decimal("19") / Decimal("100"),        # 0.19
        RARE:    Decimal("0.99999") / Decimal("100"),   # 0.0099999
    }
    p_tr = {TRES_RARE: Decimal(1) / Decimal(100000)}     # 0.00001

    # Masse des catégories autorisées
    mass = Decimal(0)
    for b, p in p_base.items():
        if elig.get(b, False):
            mass += p
    if elig.get(TRES_RARE, False):
        mass += p_tr[TRES_RARE]

    # Aucun bucket autorisé -> fallback lisible
    if mass == 0:
        return {
            SOUVENT:   Decimal(100),
            MOYEN:     Decimal(0),
            RARE:      Decimal(0),
            TRES_RARE: Decimal(0),
        }

    # Renormalisation -> la somme fait exactement 100
    return {
        SOUVENT:   (p_base[SOUVENT] / mass) * Decimal(100) if elig.get(SOUVENT, False)   else Decimal(0),
        MOYEN:     (p_base[MOYEN]   / mass) * Decimal(100) if elig.get(MOYEN,   False)   else Decimal(0),
        RARE:      (p_base[RARE]    / mass) * Decimal(100) if elig.get(RARE,    False)   else Decimal(0),
        TRES_RARE: (p_tr[TRES_RARE] / mass) * Decimal(100) if elig.get(TRES_RARE, False) else Decimal(0),
    }


