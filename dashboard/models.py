# dashboard/models.py
from django.db import models
from django.utils import timezone
from accounts.models import Company
from django.core.exceptions import ValidationError
from django.db.models import Q, F

class Client(models.Model):
    company     = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="clients")
    first_name  = models.CharField(max_length=100, blank=True)
    last_name   = models.CharField(max_length=100, blank=True)
    email       = models.EmailField(blank=True, null=True)
    phone       = models.CharField(max_length=32, blank=True)
    is_referrer = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.last_name} {self.first_name}".strip() or self.email or f"Client #{self.pk}"


class Referral(models.Model):
 
    company    = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="referrals")
    referrer   = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="referrals_made")
    referee    = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="referrals_received")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
        ]

    def __str__(self):
        return f"{self.referrer} → {self.referee} ({self.company})"

