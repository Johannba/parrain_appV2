# rewards/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Reward, RewardTemplate
from dashboard.models import Referral

# --- Déjà présent ---
@receiver(pre_save, sender=Reward)
def reward_token_autogen(sender, instance: Reward, **kwargs):
    if not instance.token:
        instance.ensure_token()

# --- Nouveau : impose le minimum requis pour les récompenses du PARRAIN ---
@receiver(pre_save, sender=Reward)
def enforce_minimum_for_referrer(sender, instance: Reward, **kwargs):
    """
    Si la reward est liée à un parrainage ET destinée au PARRAIN,
    on vérifie le minimum requis (min_referrals_required) sur le bucket ciblé.
    - Si min=0 => OK
    - Si min>0 et non atteint => neutralise la reward (DISABLED + NO_HIT + label '—')
    """
    # 1) On ne s’applique qu’aux rewards venant d’un parrainage
    if not instance.referral_id:
        return

    # 2) Charge la relation (évite plusieurs hits si déjà fetch)
    referral = getattr(instance, "referral", None)
    if referral is None:
        try:
            referral = Referral.objects.select_related("company", "referrer", "referee").get(pk=instance.referral_id)
        except Referral.DoesNotExist:
            return

    # 3) On ne cible QUE la récompense du PARRAIN
    if not referral.referrer_id or instance.client_id != referral.referrer_id:
        return

    company = referral.company
    bucket = (instance.bucket or "").upper()
    if bucket not in {"SOUVENT", "MOYEN", "RARE", "TRES_RARE"}:
        # Rien à faire pour NO_HIT, vide, etc.
        return

    # 4) Compte des parrainages du parrain (dans l’entreprise)
    #    NB: si ton "minimum" doit compter uniquement les parrainages VALIDÉS,
    #    remplace par un filtre sur ton champ de statut si tu en as un.
    ref_count = Referral.objects.filter(company=company, referrer_id=referral.referrer_id).count()

    # 5) Minimum requis du bucket visé
    tpl = RewardTemplate.objects.filter(company=company, bucket=bucket).only("min_referrals_required").first()
    min_required = int(getattr(tpl, "min_referrals_required", 0) or 0)

    # 6) Non éligible -> neutraliser proprement la Reward
    if min_required > 0 and ref_count < min_required:
        instance.bucket = "NO_HIT"
        instance.label = "—"
        instance.state = "DISABLED"
        # on laisse le token se générer (utile pour debug), mais la reward ne comptera pas
