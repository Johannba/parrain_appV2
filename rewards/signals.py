# rewards/signals.py
from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import Reward

@receiver(pre_save, sender=Reward)
def reward_token_autogen(sender, instance: Reward, **kwargs):
    if not instance.token:
        instance.ensure_token()
