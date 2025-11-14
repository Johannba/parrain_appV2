from __future__ import annotations

from django.utils import timezone

from rewards.models import RewardTemplate, Reward
from .probabilities import tirer_recompense_with_normalization, NO_HIT

__all__ = [
    "award_both_parties",
    "tirer_recompense_with_normalization",
    "NO_HIT",
]


def award_both_parties(*, referral):
    """
    Crée les récompenses PARRAIN et FILLEUL pour un parrainage donné.

    - Filleul : cadeau envoyé immédiatement (state='SENT').
    - Parrain : bucket tiré via tirer_recompense_with_normalization
                (minimums + normalisation).
                Si aucun bucket n'est éligible -> pas de reward parrain.

    Retourne un tuple (reward_parrain | None, reward_filleul).
    """
    company = referral.company
    referrer = referral.referrer
    referee = referral.referee

    # --- Reward FILLEUL : toujours attribuée ---
    tpl_referee = (
        RewardTemplate.objects.filter(company=company, bucket="SOUVENT").first()
        or RewardTemplate.objects.filter(company=company).first()
    )
    if not tpl_referee:
        raise ValueError("Aucun modèle de récompense configuré pour cette entreprise.")

    reward_filleul = Reward.objects.create(
        company=company,
        client=referee,
        bucket=tpl_referee.bucket,
        label=tpl_referee.label or "Cadeau",
        state="SENT",
        referral=referral,
    )

    update_fields = []
    if hasattr(reward_filleul, "sent_at") and not getattr(reward_filleul, "sent_at", None):
        reward_filleul.sent_at = timezone.now()
        update_fields.append("sent_at")
    if hasattr(reward_filleul, "redeemed_at") and not getattr(reward_filleul, "redeemed_at", None):
        reward_filleul.redeemed_at = timezone.now()
        update_fields.append("redeemed_at")
    if update_fields:
        reward_filleul.save(update_fields=update_fields)

    # --- Reward PARRAIN : soumise aux minimums ---
    bucket = tirer_recompense_with_normalization(company, referrer)

    if bucket == NO_HIT:
        # minimum non atteint -> pas de reward parrain
        reward_parrain = None
    else:
        tpl_referrer = RewardTemplate.objects.filter(company=company, bucket=bucket).first()

        if not tpl_referrer:
            # Si aucun min strict, on autorise un fallback sur SOUVENT
            has_min_gt0 = RewardTemplate.objects.filter(
                company=company, min_referrals_required__gt=0
            ).exists()
            if not has_min_gt0:
                tpl_referrer = (
                    RewardTemplate.objects.filter(company=company, bucket="SOUVENT").first()
                    or RewardTemplate.objects.filter(company=company).first()
                )
                if tpl_referrer:
                    bucket = tpl_referrer.bucket

        if not tpl_referrer:
            # Toujours aucun template -> on ne crée pas de reward parrain
            reward_parrain = None
        else:
            reward_parrain = Reward.objects.create(
                company=company,
                client=referrer,
                bucket=bucket,
                label=tpl_referrer.label or "Cadeau",
                state="PENDING",
                referral=referral,
            )

    return reward_parrain, reward_filleul
