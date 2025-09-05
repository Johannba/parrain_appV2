import pytest
from decimal import Decimal
from django.utils import timezone

from accounts.models import Company
from dashboard.models import Client, Referral
from rewards.models import RewardTemplate
from rewards.services.probabilities import (
    get_normalized_percentages, tirer_recompense,
    SOUVENT, MOYEN, RARE, TRES_RARE, ensure_wheels
)

pytestmark = pytest.mark.django_db

def _mk_company_with_templates(name="Acme"):
    c = Company.objects.create(name=name, slug=name.lower())
    # Probabilité affichée = purement indicatif, min_referrals_required = clés du test
    RewardTemplate.objects.create(company=c, bucket="SOUVENT",   label="-10%", cooldown_months=1, min_referrals_required=0, probability_display="980/1000")
    RewardTemplate.objects.create(company=c, bucket="MOYEN",     label="-20%", cooldown_months=1, min_referrals_required=0, probability_display="19/1000")
    RewardTemplate.objects.create(company=c, bucket="RARE",      label="iPhone", cooldown_months=3, min_referrals_required=10, probability_display="1/1000")
    RewardTemplate.objects.create(company=c, bucket="TRES_RARE", label="Miami",  cooldown_months=6, min_referrals_required=12, probability_display="1/100000")
    ensure_wheels(c)  # construit les roues exactes (1000 / 100000)
    return c

def _seed_referrals(company, referrer, n):
    """Crée n parrainages dont `referrer` est PARRAIN (on se fiche du filleul ici)."""
    for i in range(n):
        referee = Client.objects.create(company=company, first_name=f"F{i}", last_name="X")
        Referral.objects.create(
            company=company,
            referrer=referrer,
            referee=referee,
            created_at=timezone.now(),
        )

def test_normalization_when_rare_and_very_rare_blocked():
    """
    Seuils: RARE=10, TRES_RARE=12. Le client a 9 parrainages:
    -> RARE/TRES_RARE inéligibles, renormalisation sur SOUVENT/MOYEN
    Attendu:
      SOUVENT = (980/1000) / 0.99 * 100 = 80.808080...
      MOYEN   = ( 19/1000) / 0.99 * 100 = 19.191919...
    """
    c = _mk_company_with_templates()
    client = Client.objects.create(company=c, first_name="A", last_name="B")
    _seed_referrals(c, client, 9)  # 9 parrainages => RARE/TRES_RARE bloqués

    pct = get_normalized_percentages(c, client)
    assert pytest.approx(float(pct[SOUVENT]), rel=1e-9) == 80.8080808080808
    assert pytest.approx(float(pct[MOYEN]),   rel=1e-9) == 19.1919191919192
    assert pct[RARE] == Decimal("0")
    assert pct[TRES_RARE] == Decimal("0")

def test_tirer_recompense_skips_ineligible():
    """
    Vérifie que le tirage ne renvoie JAMAIS un bucket inéligible.
    Avec 9 parrainages -> RARE/TRES_RARE interdits.
    On consomme quelques tirages pour s'assurer que le curseur saute bien.
    """
    c = _mk_company_with_templates()
    client = Client.objects.create(company=c, first_name="A", last_name="B")
    _seed_referrals(c, client, 9)

    # On tire plusieurs fois: jamais RARE ni TRES_RARE
    for _ in range(1200):
        b = tirer_recompense(c, client)
        assert b in {SOUVENT, MOYEN}
