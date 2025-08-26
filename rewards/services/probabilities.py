# rewards/services/probabilities.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

from django.db import transaction

from accounts.models import Company
from rewards.models import ProbabilityWheel

# ⚠️ On garde les mêmes clés pour compatibilité (vues/templates/urls),
#    mais on va désormais construire des pools de 1000 et 100_000 cases.
BASE_KEY = "base_100"
VERY_RARE_KEY = "very_rare_10000"

# Tokens standardisés
SOUVENT = "SOUVENT"
MOYEN = "MOYEN"
RARE = "RARE"
TRES_RARE = "TRES_RARE"
NO_HIT = "NO_HIT"

# -----------------------------
#   Composition EXACTE des pools
# -----------------------------
# Base = 1000 cases -> Rare = 1/1000 (0,1 %)
# Répartition choisie (simple et lisible) :
#   - 980 x Souvent
#   -  19 x Moyen
#   -   1 x Rare
BASE_COUNTS = {
    SOUVENT: 980,
    MOYEN: 19,
    RARE: 1,
}
BASE_SIZE = sum(BASE_COUNTS.values())  # 1000

# Très rare = 100_000 cases -> 1/100_000 (0,001 %)
VR_COUNTS = {
    NO_HIT: 100_000 - 1,
    TRES_RARE: 1,
}
VR_SIZE = sum(VR_COUNTS.values())  # 100_000


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
    Crée (ou met à niveau) les deux roues pour l’entreprise.
    - BASE_KEY      -> 1000 cases (980/19/1)
    - VERY_RARE_KEY -> 100_000 cases (1 TRES_RARE)
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

    # Mise à niveau si l’ancienne taille (100 / 10_000) est encore en base
    if base.size != BASE_SIZE:
        base.pool, base.size, base.idx = _build_base_pool(), BASE_SIZE, 0
        base.save(update_fields=["pool", "size", "idx"])

    if very_rare.size != VR_SIZE:
        very_rare.pool, very_rare.size, very_rare.idx = _build_very_rare_pool(), VR_SIZE, 0
        very_rare.save(update_fields=["pool", "size", "idx"])

    return base, very_rare


def rebuild_wheel(company: Company, key: str) -> None:
    """Régénère entièrement une roue (repart à idx=0)."""
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
    """Remet le curseur à zéro (sans toucher la composition)."""
    wheel = ProbabilityWheel.objects.get(company=company, key=key)
    wheel.idx = 0
    wheel.save(update_fields=["idx"])


def _consume_one(wheel: ProbabilityWheel) -> str:
    value = wheel.pool[wheel.idx]
    wheel.idx = (wheel.idx + 1) % wheel.size
    wheel.save(update_fields=["idx"])
    return value


def tirer_recompense(company: Company) -> str:
    """
    Tirage déterministe EXACT (pas d’aléatoire) :
      1) On consomme la roue VERY_RARE_KEY (1 / 100_000 par cycle).
         -> si TRES_RARE : on retourne immédiatement TRES_RARE
      2) Sinon, on consomme la roue BASE_KEY (980/19/1 sur 1000 exactement).
    """
    base, very_rare = ensure_wheels(company)
    vr = _consume_one(very_rare)
    if vr == TRES_RARE:
        return TRES_RARE
    return _consume_one(base)


@dataclass
class WheelSnapshot:
    size: int
    idx: int
    progress_pct: int
    remaining_by_token: Dict[str, int]
    total_by_token: Dict[str, int]


def _remaining_counts(pool: List[str], idx: int, tokens: List[str]) -> Dict[str, int]:
    """Compte ce qu'il reste AVANT la fin du cycle actuel (de idx -> fin)."""
    tail = pool[idx:]
    out: Dict[str, int] = {}
    for t in tokens:
        out[t] = tail.count(t)
    return out


def get_snapshot(company: Company) -> Dict[str, WheelSnapshot]:
    """Données pour l’UI (progression et restants par token)."""
    base, very_rare = ensure_wheels(company)

    base_tokens = [SOUVENT, MOYEN, RARE]
    base_total = {t: base.pool.count(t) for t in base_tokens}
    base_remaining = _remaining_counts(base.pool, base.idx, base_tokens)

    vr_tokens = [TRES_RARE, NO_HIT]
    vr_total = {t: very_rare.pool.count(t) for t in vr_tokens}
    vr_remaining = _remaining_counts(very_rare.pool, very_rare.idx, vr_tokens)

    return {
        "base": WheelSnapshot(
            size=base.size,
            idx=base.idx,
            progress_pct=int((base.idx / base.size) * 100) if base.size else 0,
            remaining_by_token=base_remaining,
            total_by_token=base_total,
        ),
        "very_rare": WheelSnapshot(
            size=very_rare.size,
            idx=very_rare.idx,
            progress_pct=int((very_rare.idx / very_rare.size) * 100) if very_rare.size else 0,
            remaining_by_token=vr_remaining,
            total_by_token=vr_total,
        ),
    }
