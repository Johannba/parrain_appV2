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
        # ❗ Un filleul (referee) ne peut exister qu'une seule fois par entreprise
        constraints = [
            models.UniqueConstraint(
                fields=["company", "referee"],
                name="uniq_referee_per_company",
            )
        ]

    def __str__(self):
        return f"{self.referrer} → {self.referee} ({self.company})"

class Reward(models.Model):
    """Récompense attribuée à un client (souvent le parrain)."""
    STATE_CHOICES = [
        ("PENDING", "À envoyer"),
        ("SENT", "Envoyé"),
        ("DISABLED", "Désactivé"),
        ("ARCHIVED", "Archivé"),
    ]
    company    = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rewards")
    client     = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="rewards")
    label      = models.CharField(max_length=200)            # ex: "-10% sur 1 achat"
    code       = models.CharField(max_length=64, blank=True) # ex: "AB-123-456"
    channel    = models.CharField(max_length=32, blank=True) # ex: "Mail", "SMS"…
    state      = models.CharField(max_length=16, choices=STATE_CHOICES, default="PENDING")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.label} ({self.get_state_display()})"
