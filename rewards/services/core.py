# rewards/services/core.py
from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from ..models import RewardTemplate, Reward  # ⬅️ import relatif (note les deux points)


def create_reward_from_template(*, company, client, tpl, referral=None, label=None) -> Reward:
    """
    Crée une Reward à partir d’un RewardTemplate en recopiant le cooldown_days.
    Idempotent ? -> Non. Si tu veux éviter les doublons, vérifie avant.
    """
    reward = Reward(
        company=company,
        client=client,
        referral=referral,
        label=label or tpl.label,
        bucket=tpl.bucket,
        cooldown_days=tpl.cooldown_days or 0,
        state="PENDING",
    )
    reward.ensure_token()
    # Optionnel : aligner expiration du lien sur le délai d’utilisation
    if reward.cooldown_days and not reward.token_expires_at:
        reward.token_expires_at = timezone.now() + timedelta(days=int(reward.cooldown_days))
    reward.save()
    return reward


@transaction.atomic
def award_both_parties(*, referral, bucket_referrer="SOUVENT", bucket_referee="SOUVENT"):
    """
    Attribue une récompense au parrain ET au filleul pour un même Referral.
    - Par défaut, même bucket pour les deux ('SOUVENT'). Change si besoin.
    - Idempotent au niveau (company, client, referral) grâce à une vérif avant création.
    """
    company = referral.company
    referrer = referral.referrer
    referee = referral.referee

    # Choix des templates (tu peux changer la logique de sélection ici)
    tpl_referrer = RewardTemplate.objects.get(company=company, bucket=bucket_referrer)
    tpl_referee  = RewardTemplate.objects.get(company=company, bucket=bucket_referee)

    # Évite doublons : unique (company, client, referral)
    reward_referrer = Reward.objects.filter(company=company, client=referrer, referral=referral).first()
    if not reward_referrer:
        reward_referrer = create_reward_from_template(
            company=company, client=referrer, tpl=tpl_referrer, referral=referral
        )

    reward_referee = Reward.objects.filter(company=company, client=referee, referral=referral).first()
    if not reward_referee:
        reward_referee = create_reward_from_template(
            company=company, client=referee, tpl=tpl_referee, referral=referral
        )

    return reward_referrer, reward_referee
