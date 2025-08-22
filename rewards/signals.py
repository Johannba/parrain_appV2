# rewards/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver
from dashboard.models import Reward


@receiver(pre_save, sender=Reward)
def reward_set_company_from_client(sender, instance, **kwargs):
    """
    Avant d’enregistrer une Reward :
    - si le client est défini,
    - on aligne automatiquement company = client.company
    """
    if instance.client and instance.client.company:
        instance.company = instance.client.company
