from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable, List, Tuple
from django.db import transaction
from django.utils.text import slugify
from rewards.models import ProbabilityWheel
from accounts.models import Company

# --------- Utilitaires de pool ----------
def build_pool(pairs: Iterable[Tuple[int, str]]) -> List[str]:
    """
    Construit une liste ordonnée à partir de paires (occurences, valeur).
    Exemple: [(80,'Souvent'), (20,'NO_HIT')] -> 100 cases.
    """
    pool: List[str] = []
    for n, val in pairs:
        if n < 0:
            raise ValueError("n négatif")
        pool.extend([val] * n)
    return pool

def interleave(pool: List[str]) -> List[str]:
    """
    Ré-ordonne le pool pour mieux répartir les valeurs (évite les clusters).
    Stratégie simple: round-robin par groupes.
    """
    # On groupe par valeur
    from collections import defaultdict, deque
    buckets = defaultdict(deque)
    for v in pool:
        buckets[v].append(v)

    # On itère tant qu'il reste des éléments
    keys = sorted(buckets.keys(), key=lambda k: -len(buckets[k]))
    out: List[str] = []
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                out.append(buckets[k].popleft())
    return out

# --------- API principale ----------
@dataclass
class WheelSpec:
    key: str
    # paires (occurences, label)
    pairs: Tuple[Tuple[int, str], ...]

def ensure_wheel(company: Company, spec: WheelSpec) -> ProbabilityWheel:
    """
    Crée ou met à jour la roue pour une entreprise donnée, selon la spec.
    """
    key = slugify(spec.key)
    raw = build_pool(spec.pairs)
    pool = interleave(raw) if len(set(raw)) > 1 else raw
    with transaction.atomic():
        obj, _created = ProbabilityWheel.objects.select_for_update().get_or_create(
            company=company, key=key, defaults={"pool": pool, "size": len(pool), "idx": 0}
        )
        # Si la taille/def change, on remplace
        if obj.size != len(pool) or obj.pool != pool:
            obj.pool = pool
            obj.size = len(pool)
            # on préserve l’idx modulo la nouvelle taille
            obj.idx = obj.idx % (len(pool) or 1)
            obj.save(update_fields=["pool", "size", "idx"])
    return obj

def draw(company: Company, key: str) -> str:
    """
    Tire le prochain élément de la roue (déterministe, tourniquet), puis avance l’idx.
    """
    k = slugify(key)
    with transaction.atomic():
        wheel = ProbabilityWheel.objects.select_for_update().get(company=company, key=k)
        if wheel.size == 0:
            raise ValueError("Roue vide")
        value = wheel.pool[wheel.idx]
        wheel.idx = (wheel.idx + 1) % wheel.size
        wheel.save(update_fields=["idx"])
        return value

# --------- Specs prêtes à l’emploi ----------
BASE_100 = WheelSpec(
    key="base_100",
    pairs=((80, "Souvent"), (19, "Moyen"), (1, "Rare")),
)
VERY_RARE_10000 = WheelSpec(
    key="very_rare_10000",
    pairs=((9999, "NO_HIT"), (1, "Très rare")),
)
