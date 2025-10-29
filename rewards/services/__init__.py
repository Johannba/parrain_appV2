# rewards/services/__init__.py
from __future__ import annotations
from django.db import transaction
from rewards.models import Reward, RewardTemplate
from rewards.services.probabilities import (
    tirer_recompense, NO_HIT, SOUVENT, MOYEN, RARE, TRES_RARE
)

@transaction.atomic
def award_both_parties(*, referral):
    """
    Attribue les récompenses:
      - Filleul : toujours un cadeau (bucket SOUVENT par défaut).
      - Parrain : cadeau SEULEMENT si un bucket est éligible (sinon None).
    Retourne (reward_parrain | None, reward_filleul).
    """
    company = referral.company
    referrer = referral.referrer
    referee  = referral.referee

    # ------ Parrain : respecte min_referrals_required ------
    bucket_referrer = tirer_recompense(company, referrer)
    reward_parrain = None
    if bucket_referrer != NO_HIT:
        tpl = RewardTemplate.objects.filter(company=company, bucket=bucket_referrer).first()
        if tpl:
            reward_parrain, _ = Reward.objects.get_or_create(
                company=company,
                client=referrer,
                referral=referral,
                defaults={
                    "label": tpl.label,
                    "bucket": bucket_referrer,
                    "cooldown_days": getattr(tpl, "cooldown_days", 0) or 0,
                    "state": "PENDING",
                },
            )

    # ------ Filleul : cadeau immédiat (souvent) ------
    tpl_referee = (
        RewardTemplate.objects.filter(company=company, bucket=SOUVENT).first()
        or RewardTemplate.objects.filter(company=company).order_by("bucket").first()
    )
    if not tpl_referee:
        raise RuntimeError("Aucun RewardTemplate défini pour cette entreprise.")

    reward_filleul, _ = Reward.objects.get_or_create(
        company=company,
        client=referee,
        referral=referral,
        defaults={
            "label": tpl_referee.label,
            "bucket": tpl_referee.bucket,
            "cooldown_days": getattr(tpl_referee, "cooldown_days", 0) or 0,
            "state": "PENDING",
        },
    )

    return reward_parrain, reward_filleul
