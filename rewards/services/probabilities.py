# rewards/services/probabilities.py
from __future__ import annotations

from dataclasses import dataclass  # compat legacy (exposé plus bas)
from decimal import Decimal, getcontext
from typing import Dict, List, Tuple, Set

from django.db import transaction
from django.shortcuts import render  # inoffensif si non utilisé

from accounts.models import Company
from rewards.models import ProbabilityWheel, RewardTemplate
from dashboard.models import Referral
import random

# ---------- Compatibilité historique avec rewards.probabilities ----------
from rewards.probabilities import (  # type: ignore
    WheelSpec as _LegacyWheelSpec,
    ensure_wheel as _legacy_ensure_wheel,
    draw as _legacy_draw,
)
from django.db.models import Max
import logging

logger = logging.getLogger(__name__)


# Exposition des symboles historiques
WheelSpec = _LegacyWheelSpec
ensure_wheel = _legacy_ensure_wheel
draw = _legacy_draw

__all__ = [
    # Constantes / clés
    "BASE_KEY", "VERY_RARE_KEY",
    "SOUVENT", "MOYEN", "RARE", "TRES_RARE", "NO_HIT",
    "BASE_COUNTS", "BASE_SIZE", "VR_COUNTS", "VR_SIZE",
    # API roues exactes
    "ensure_wheels", "rebuild_wheel", "reset_wheel",
    # Tirage métier + affichage
    "tirer_recompense",
    "get_normalized_percentages",
    "tirer_recompense_with_normalization",
    # Compat
    "WheelSpec", "ensure_wheel", "draw",
]

# ------------------ Définition des deux roues “exactes” ------------------
BASE_KEY = "base_100"               # 1 000 cases = 980 / 19 / 1
VERY_RARE_KEY = "very_rare_10000"   # 100 000 cases = 1 très rare

SOUVENT = "SOUVENT"
MOYEN = "MOYEN"
RARE = "RARE"
TRES_RARE = "TRES_RARE"
NO_HIT = "NO_HIT"

BASE_COUNTS: Dict[str, int] = {SOUVENT: 980, MOYEN: 19, RARE: 1}
BASE_SIZE: int = sum(BASE_COUNTS.values())  # 1000

VR_COUNTS: Dict[str, int] = {NO_HIT: 100_000 - 1, TRES_RARE: 1}
VR_SIZE: int = sum(VR_COUNTS.values())  # 100_000

# Précision confortable pour les calculs de pourcentages
getcontext().prec = 28


# ------------------ Construction (pools) ------------------
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


# ------------------ Création / maintenance des roues ------------------
@transaction.atomic
def ensure_wheels(company: Company) -> Tuple[ProbabilityWheel, ProbabilityWheel]:
    """
    Crée (ou met à niveau) les deux roues exactes pour l’entreprise :
      - base_100      (SOUVENT/MOYEN/RARE) 980/19/1
      - very_rare_10000 (TRES_RARE vs NO_HIT) 1/100000
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

    if base.size != BASE_SIZE or len(base.pool) != BASE_SIZE:
        base.pool, base.size, base.idx = _build_base_pool(), BASE_SIZE, 0
        base.save(update_fields=["pool", "size", "idx"])

    if very_rare.size != VR_SIZE or len(very_rare.pool) != VR_SIZE:
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
        company=company, key=key, defaults={"pool": pool, "size": size, "idx": 0}
    )


def reset_wheel(company: Company, key: str) -> None:
    wheel = ProbabilityWheel.objects.get(company=company, key=key)
    wheel.idx = 0
    wheel.save(update_fields=["idx"])


# ------------------ Éligibilité par minimums ------------------
def _eligible_buckets_for(company: Company, client) -> Dict[str, bool]:
    """
    Retourne l'éligibilité par bucket, SANS bloquer globalement.

    - On compte le nombre de parrainages du client dans l’entreprise.
    - Pour chaque bucket, on prend le MAX des min_referrals_required
      (utile s’il y a des doublons de templates).
    - Un bucket est éligible si referrals_count >= min_required.
    """
    # Nombre de parrainages de ce client dans cette entreprise
    referrals_count = Referral.objects.filter(company=company, referrer=client).count()

    # Agrégation par bucket : on prend le max des minimums configurés
    agg = (
        RewardTemplate.objects
        .filter(company=company)
        .values("bucket")
        .annotate(min_required=Max("min_referrals_required"))
    )
    thresholds: Dict[str, int] = {
        row["bucket"]: int(row["min_required"] or 0) for row in agg
    }

    def is_ok(bucket: str) -> bool:
        min_required = thresholds.get(bucket)
        if min_required is None:
            # pas de template pour ce bucket -> non éligible
            return False
        return referrals_count >= min_required

    elig = {
        SOUVENT:   is_ok(SOUVENT),
        MOYEN:     is_ok(MOYEN),
        RARE:      is_ok(RARE),
        TRES_RARE: is_ok(TRES_RARE),
    }

    # Log debug utile pour vérifier ce qui se passe en vrai
    logger.warning(
        "ELIG company=%s client=%s referrals=%s thresholds=%s elig=%s",
        getattr(company, "id", None),
        getattr(client, "id", None),
        referrals_count,
        thresholds,
        elig,
    )

    return elig




# ------------------ Consommation “avec saut” ------------------
def _consume_one_eligible(wheel: ProbabilityWheel, allowed: Set[str]) -> str:
    """
    Consomme la roue cyclique en sautant les cases non autorisées.
    Si rien n’est autorisé sur un tour complet → NO_HIT.
    """
    if wheel.size == 0:
        raise ValueError("Roue vide")

    for _ in range(wheel.size):
        val = wheel.pool[wheel.idx]
        wheel.idx = (wheel.idx + 1) % wheel.size
        if val in allowed:
            wheel.save(update_fields=["idx"])
            return val

    # Aucun résultat autorisé rencontré : on a fait un tour complet.
    wheel.save(update_fields=["idx"])
    return NO_HIT


# ------------------ Tirage principal ------------------
def tirer_recompense(company: Company, client) -> str:
    """
    Combine la roue VERY_RARE (1/100000) puis, en cas d’échec, la roue BASE.
    On respecte les minimums (éligibilité) en sautant les cases non autorisées.
    """
    elig = _eligible_buckets_for(company, client)
    base, very_rare = ensure_wheels(company)

    # VERY RARE : autoriser TRES_RARE seulement si éligible
    allowed_vr: Set[str] = {NO_HIT}
    if elig.get(TRES_RARE, False):
        allowed_vr.add(TRES_RARE)

    vr = _consume_one_eligible(very_rare, allowed_vr)
    if vr == TRES_RARE:
        return TRES_RARE

    # BASE : autoriser uniquement les buckets éligibles
    allowed_base: Set[str] = set()
    if elig.get(SOUVENT, False):
        allowed_base.add(SOUVENT)
    if elig.get(MOYEN, False):
        allowed_base.add(MOYEN)
    if elig.get(RARE, False):
        allowed_base.add(RARE)

    if not allowed_base:
        return NO_HIT

    return _consume_one_eligible(base, allowed_base)


# ------------------ Pourcentages UI normalisés ------------------
def get_normalized_percentages(company: Company, client) -> Dict[str, Decimal]:
    """
    Calcule les pourcentages affichés côté UI en partant des probabilités
    “canoniques” puis en RENORMALISANT pour sommer à 100, selon l’éligibilité.

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

    # Masse totale autorisée
    mass = Decimal(0)
    for b, p in p_base.items():
        if elig.get(b, False):
            mass += p
    if elig.get(TRES_RARE, False):
        mass += p_tr[TRES_RARE]

    if mass == 0:
        return {SOUVENT: Decimal(0), MOYEN: Decimal(0), RARE: Decimal(0), TRES_RARE: Decimal(0)}

    # Renormalisation pour sommer à 100
    return {
        SOUVENT:   (p_base[SOUVENT] / mass) * Decimal(100) if elig.get(SOUVENT, False)   else Decimal(0),
        MOYEN:     (p_base[MOYEN]   / mass) * Decimal(100) if elig.get(MOYEN,   False)   else Decimal(0),
        RARE:      (p_base[RARE]    / mass) * Decimal(100) if elig.get(RARE,    False)   else Decimal(0),
        TRES_RARE: (p_tr[TRES_RARE] / mass) * Decimal(100) if elig.get(TRES_RARE, False) else Decimal(0),
    }
def tirer_recompense_with_normalization(company: Company, client) -> str:
    """
    Tirage « mathématique » :

    1. On part des probabilités canoniques :
         - SOUVENT   = 80 / 100
         - MOYEN     = 19 / 100
         - RARE      = 0,99999 / 100
         - TRES_RARE = 1 / 100000
    2. On enlève les buckets dont le minimum n'est pas atteint
       (via _eligible_buckets_for).
    3. On RENORMALISE pour que la somme fasse 100.
    4. On tire un bucket pondéré.

    Si aucun bucket n'est éligible → NO_HIT.
    """
    # Pourcentages déjà normalisés côté UI (0..100)
    pct = get_normalized_percentages(company, client)
    total = sum(pct.values())

    if total <= 0:
        return NO_HIT

    # tirage dans [0 ; total) (en pratique total ≈ 100)
    x = Decimal(str(random.random())) * total
    acc = Decimal("0")

    for bucket in (SOUVENT, MOYEN, RARE, TRES_RARE):
        p = pct.get(bucket, Decimal("0"))
        if p <= 0:
            continue
        acc += p
        if x < acc:
            return bucket

    # garde-fou numérique
    for bucket in (TRES_RARE, RARE, MOYEN, SOUVENT):
        if pct.get(bucket, Decimal("0")) > 0:
            return bucket

    return NO_HIT
