from django.db.models.signals import post_save
from django.dispatch import receiver
from accounts.models import Company
from rewards.services.probabilities import ensure_wheels_for_company
from dashboard.models import Client
from .utils import should_skip_client_user_autocreate

@receiver(post_save, sender=Company)
def init_probability_wheels(sender, instance: Company, created, **kwargs):
    if created:
        ensure_wheels_for_company(instance)


