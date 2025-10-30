# rewards/services/award.py
from __future__ import annotations
from typing import Tuple
from django.db import transaction
from django.utils import timezone

from accounts.models import Company
from dashboard.models import Referral, Client
from rewards.models import Reward, RewardTemplate
from rewards.services.probabilities import (
    tirer_recompense, NO_HIT, SOUVENT, MOYEN, RARE, TRES_RARE
)

@transaction.atomic
def award_both_parties(*, referral: Referral) -> Tuple[Reward, Reward]:
    """
    Attribue 2 récompenses pour un parrainage donné (idempotent) :
      - FILLEUL : toujours un cadeau (bucket SOUVENT), que tu passeras à SENT immédiatement.
      - PARRAIN : tirage via tirer_recompense(...). Si aucun bucket n'est éligible => NO_HIT + DISABLED.
    Retourne (reward_parrain, reward_filleul).
    """
    company: Company = referral.company
    referrer: Client = referral.referrer
    referee:  Client = referral.referee

    # --- FILLEUL : cadeau certain (SOUVENT) ---
    tpl_referee = RewardTemplate.objects.filter(company=company, bucket=SOUVENT).first()
    label_referee = (tpl_referee.label if tpl_referee and tpl_referee.label else "Cadeau")
    reward_filleul, _ = Reward.objects.get_or_create(
        company=company, client=referee, referral=referral,
        defaults={"label": label_referee, "bucket": SOUVENT, "state": "PENDING"},
    )

    # --- PARRAIN : respect des minimums via tirer_recompense ---
    hit = tirer_recompense(company=company, client=referrer)  # => SOUVENT/MOYEN/RARE/TRES_RARE ou NO_HIT
    if hit == NO_HIT:
        # On garde une trace neutre (DISABLED) pour ne pas polluer KPI/historiques
        reward_parrain, _ = Reward.objects.get_or_create(
            company=company, client=referrer, referral=referral,
            defaults={"label": "—", "bucket": NO_HIT, "state": "DISABLED"},
        )
        if reward_parrain.state != "DISABLED":
            reward_parrain.label = "—"
            reward_parrain.bucket = NO_HIT
            reward_parrain.state = "DISABLED"
            reward_parrain.save(update_fields=["label", "bucket", "state"])
        return reward_parrain, reward_filleul

    # Bucket gagnant -> label depuis le template correspondant
    tpl = RewardTemplate.objects.filter(company=company, bucket=hit).first()
    label = (tpl.label if tpl and tpl.label else hit.title())
    reward_parrain, _ = Reward.objects.get_or_create(
        company=company, client=referrer, referral=referral,
        defaults={"label": label, "bucket": hit, "state": "PENDING"},
    )
    # Normalisation si existait autrement
    changed = False
    if reward_parrain.bucket != hit:
        reward_parrain.bucket = hit; changed = True
    if reward_parrain.label != label:
        reward_parrain.label = label; changed = True
    if changed:
        reward_parrain.save(update_fields=["bucket", "label"])

    return reward_parrain, reward_filleul
