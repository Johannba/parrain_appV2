# dashboard/models.py
from django.db import models
from django.utils import timezone
from accounts.models import Company  # tu l’as déjà

class Client(models.Model):
    company     = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="clients")
    first_name  = models.CharField(max_length=150, blank=True)
    last_name   = models.CharField(max_length=150, blank=True)
    email       = models.EmailField(blank=True)
    phone       = models.CharField(max_length=32, blank=True)
    is_referrer = models.BooleanField(default=False)  # parrain ?

    class Meta:
        ordering = ["last_name", "first_name"]
        unique_together = [("company", "email")]  # optionnel : protège les doublons par email dans une entreprise

    def __str__(self):
        full = f"{self.last_name} {self.first_name}".strip()
        return full or self.email or f"Client #{self.pk}"

class Referral(models.Model):
    """Un parrain (referrer) parraine un filleul (referee) dans une entreprise."""
    STATUS_CHOICES = [
        ("PENDING", "En attente"),
        ("APPROVED", "Validé"),
        ("REJECTED", "Rejeté"),
    ]
    company    = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="referrals")
    referrer   = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="referrals_made")
    referee    = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="referrals_received")
    status     = models.CharField(max_length=16, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.referrer} → {self.referee} ({self.get_status_display()})"

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
