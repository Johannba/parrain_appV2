# rewards/services/probabilities.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple

from django.db import transaction

from accounts.models import Company
from rewards.models import ProbabilityWheel

BASE_KEY = "base_100"
VERY_RARE_KEY = "very_rare_10000"

# Tokens standardisés pour la roue
SOUVENT = "SOUVENT"
MOYEN = "MOYEN"
RARE = "RARE"
TRES_RARE = "TRES_RARE"
NO_HIT = "NO_HIT"


def _build_base_pool() -> List[str]:
    """
    100 cases au total:
      - 80 x SOUVENT
      - 19 x MOYEN
      - 1  x RARE
    """
    return [SOUVENT] * 80 + [MOYEN] * 19 + [RARE] * 1


def _build_very_rare_pool() -> List[str]:
    """
    10 000 cases:
      - 9 999 x NO_HIT
      -     1 x TRES_RARE
    """
    return [NO_HIT] * 9_999 + [TRES_RARE]


@transaction.atomic
def ensure_wheels(company: Company) -> Tuple[ProbabilityWheel, ProbabilityWheel]:
    """Crée les roues manquantes pour l’entreprise (idempotent)."""
    base, _ = ProbabilityWheel.objects.get_or_create(
        company=company,
        key=BASE_KEY,
        defaults={"pool": _build_base_pool(), "size": 100, "idx": 0},
    )
    very_rare, _ = ProbabilityWheel.objects.get_or_create(
        company=company,
        key=VERY_RARE_KEY,
        defaults={"pool": _build_very_rare_pool(), "size": 10_000, "idx": 0},
    )
    # Si pool vide / incohérente, on régénère
    if not base.pool or base.size != 100:
        base.pool, base.size, base.idx = _build_base_pool(), 100, 0
        base.save(update_fields=["pool", "size", "idx"])
    if not very_rare.pool or very_rare.size != 10_000:
        very_rare.pool, very_rare.size, very_rare.idx = _build_very_rare_pool(), 10_000, 0
        very_rare.save(update_fields=["pool", "size", "idx"])
    return base, very_rare


def rebuild_wheel(company: Company, key: str) -> None:
    """Régénère entièrement une roue pour repartir à zéro."""
    pool = _build_base_pool() if key == BASE_KEY else _build_very_rare_pool()
    size = 100 if key == BASE_KEY else 10_000
    ProbabilityWheel.objects.update_or_create(
        company=company, key=key,
        defaults={"pool": pool, "size": size, "idx": 0}
    )


def reset_wheel(company: Company, key: str) -> None:
    """Remet le curseur à zéro sans changer la composition."""
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
    Tirage déterministe EXACT :
      - On consulte d’abord la roue VERY_RARE_KEY (1 / 10 000 exactement par cycle).
      - Si NO_HIT, on consulte la roue BASE_KEY (80/19/1 sur 100 exactement).
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
    """
    Compte ce qu'il reste AVANT la fin du cycle actuel (de idx -> fin).
    """
    tail = pool[idx:]
    out: Dict[str, int] = {}
    for t in tokens:
        out[t] = tail.count(t)
    return out


def get_snapshot(company: Company) -> Dict[str, WheelSnapshot]:
    """Données pour l’UI (progress, restants par token)."""
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
            progress_pct=int((base.idx / base.size) * 100),
            remaining_by_token=base_remaining,
            total_by_token=base_total,
        ),
        "very_rare": WheelSnapshot(
            size=very_rare.size,
            idx=very_rare.idx,
            progress_pct=int((very_rare.idx / very_rare.size) * 100),
            remaining_by_token=vr_remaining,
            total_by_token=vr_total,
        ),
    }
