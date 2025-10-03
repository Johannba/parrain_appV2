# rewards/tests/test_real_draws.py
import pytest
from collections import Counter
from django.utils import timezone

from accounts.models import Company
from dashboard.models import Client, Referral
from rewards.models import RewardTemplate
from rewards.services.probabilities import (
    ensure_wheels, tirer_recompense,
    SOUVENT, MOYEN, RARE, TRES_RARE,
)

pytestmark = pytest.mark.django_db


# ----------------------------
# Helpers
# ----------------------------

def _mk_company_with_templates(
    name="Acme",
    min_rare=0,
    min_tres_rare=0,
    label_map=None,
):
    """
    Crée une entreprise + les 4 RewardTemplate avec les minimums d’éligibilité voulus.
    Les probas affichées ne servent que d'info; la vraie distribution vient des roues.
    """
    c = Company.objects.create(name=name, slug=name.lower())
    defaults = {
        SOUVENT:   {"label": "-10 %", "cooldown_months": 1, "min": 0,           "prob": "980/1000"},
        MOYEN:     {"label": "-20 %", "cooldown_months": 1, "min": 0,           "prob": "19/1000"},
        RARE:      {"label": "Rare",  "cooldown_months": 3, "min": min_rare,    "prob": "1/1000"},
        TRES_RARE: {"label": "Jackpot","cooldown_months": 6,"min": min_tres_rare,"prob": "1/100000"},
    }
    label_map = label_map or {}
    for bucket, meta in defaults.items():
        RewardTemplate.objects.create(
            company=c,
            bucket=bucket,
            label=label_map.get(bucket, meta["label"]),
            cooldown_months=meta["cooldown_months"],
            min_referrals_required=meta["min"],
            probability_display=meta["prob"],
        )
    ensure_wheels(c)  # pool base (1000) et very_rare (100000) à idx=0
    return c


def _client(company, first="A", last="B"):
    return Client.objects.create(company=company, first_name=first, last_name=last)


def _seed_referrals(company, referrer, n):
    """Crée n parrainages où `referrer` est le parrain (le filleul importe peu ici)."""
    for i in range(n):
        referee = Client.objects.create(company=company, first_name=f"F{i}", last_name="X")
        Referral.objects.create(
            company=company, referrer=referrer, referee=referee, created_at=timezone.now()
        )


def _draw_n(company, client, n):
    cnt = Counter()
    for _ in range(n):
        cnt[tirer_recompense(company, client)] += 1
    # S’assure que toutes les clés existent
    for k in (SOUVENT, MOYEN, RARE, TRES_RARE):
        cnt.setdefault(k, 0)
    return cnt


# ----------------------------
# Tests “partie réelle” (consommation des roues)
# ----------------------------

def test_first_100_draws_from_fresh_cycle_are_all_souvent():
    """
    Avec des roues neuves (idx=0) et client éligible à tout,
    les 100 premiers tirages tombent forcément sur SOUVENT (pool base ordonné).
    """
    c = _mk_company_with_templates(name="AllEligible")
    client = _client(c)
    cnt = _draw_n(c, client, 100)
    assert cnt[SOUVENT] == 100
    assert cnt[MOYEN] == cnt[RARE] == cnt[TRES_RARE] == 0


def test_full_base_cycle_1000_all_eligible_gives_980_19_1():
    """
    Sur un cycle complet de la roue base (1000 tirages) avec tout éligible :
    980 SOUVENT, 19 MOYEN, 1 RARE. TRES_RARE n’apparaît pas avant 100000 tirages.
    """
    c = _mk_company_with_templates(name="Cycle1000")  # tout éligible
    client = _client(c)
    cnt = _draw_n(c, client, 1000)
    assert cnt[SOUVENT] == 980
    assert cnt[MOYEN] == 19
    assert cnt[RARE] == 1
    assert cnt[TRES_RARE] == 0


def test_very_rare_exactly_once_per_100000_when_eligible():
    """
    Quand TRES_RARE est éligible, il sort exactement 1 fois par cycle de 100000 tirages.
    Les 99999 autres tirages consomment la roue base (99 cycles complets + 999 entrées).
    """
    c = _mk_company_with_templates(name="VeryRareEligible")
    client = _client(c)

    cnt = _draw_n(c, client, 100_000)

    # 1 seul TRES_RARE
    assert cnt[TRES_RARE] == 1

    # Répartition base attendue sur 99 cycles + 999 tirages (indices 0..998)
    # 99 cycles -> 99*980, 99*19, 99*1
    # +999 tirages -> 980 SOUVENT + 19 MOYEN
    assert cnt[SOUVENT] == 98_000   # 97_020 + 980
    assert cnt[MOYEN]   == 1_900    # 1_881 + 19
    assert cnt[RARE]    == 99       # 99
    # Somme de contrôle
    assert sum(cnt.values()) == 100_000


def test_ineligible_rare_and_very_rare_gives_981_souvent_19_moyen_on_1000():
    """
    Seuils RARE=10, TRES_RARE=12 ; client avec 9 parrainages => RARE/TRES_RARE inéligibles.
    Sur 1000 tirages, la case RARE (dernière du pool base) est “sautée” et remplacée par
    la case suivante autorisée => 981 SOUVENT, 19 MOYEN, 0 RARE, 0 TRES_RARE.
    """
    c = _mk_company_with_templates(name="MinThresholds", min_rare=10, min_tres_rare=12)
    client = _client(c)
    _seed_referrals(c, client, 9)  # inéligible à RARE/TRES_RARE

    cnt = _draw_n(c, client, 1000)
    assert cnt[SOUVENT] == 981
    assert cnt[MOYEN] == 19
    assert cnt[RARE] == 0
    assert cnt[TRES_RARE] == 0


def test_rare_becomes_eligible_at_10_but_tres_rare_not_yet():
    """
    À 10 parrainages : RARE devient éligible, pas TRES_RARE.
    On retrouve donc 980/19/1 sur 1000 tirages.
    """
    c = _mk_company_with_templates(name="RareOnly", min_rare=10, min_tres_rare=12)
    client = _client(c)
    _seed_referrals(c, client, 10)

    cnt = _draw_n(c, client, 1000)
    assert cnt[SOUVENT] == 980
    assert cnt[MOYEN] == 19
    assert cnt[RARE] == 1
    assert cnt[TRES_RARE] == 0


def test_tres_rare_apparait_juste_apres_99999_tirs_quand_il_devient_eligible():
    """
    Démonstration du “skip” propre :
    - On tire 99 999 fois alors que TRES_RARE est inéligible -> on consomme tout le NO_HIT.
    - On rend ensuite TRES_RARE éligible -> le tirage suivant tombe sur la case TRES_RARE.
    """
    # Au départ TR inéligible
    c = _mk_company_with_templates(name="EnableLater", min_rare=0, min_tres_rare=1)
    client = _client(c)

    # 0 parrainage -> TR inéligible
    cnt1 = _draw_n(c, client, 99_999)
    assert cnt1[TRES_RARE] == 0

    # Devient éligible (1 parrainage)
    _seed_referrals(c, client, 1)
    cnt2 = _draw_n(c, client, 1)
    assert cnt2[TRES_RARE] == 1
