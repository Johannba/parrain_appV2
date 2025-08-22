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

# rewards/models.py (ou dashboard/models.py si Reward est là)
from django.db import models

class Reward(models.Model):
    STATE_CHOICES = (
        ("PENDING", "À envoyer"),
        ("SENT", "Envoyé"),
        ("DISABLED", "Désactivé"),
        ("ARCHIVED", "Archivé"),
    )

    BUCKET_CHOICES = (
        ("SOUVENT", "Souvent (~80/100)"),
        ("MOYEN", "Moyen (~19/100)"),
        ("RARE", "Rare (~1/100)"),
        ("TRES_RARE", "Très rare (~1/10000)"),
    )

    company = models.ForeignKey("accounts.Company", on_delete=models.CASCADE, related_name="rewards")

    label = models.CharField(max_length=120)
    code = models.CharField(max_length=50, blank=True)
    channel = models.CharField(max_length=50, blank=True)
    state = models.CharField(max_length=12, choices=STATE_CHOICES, default="PENDING")

    # ⚠️ NE PLUS ATTRIBUER À UN CLIENT — on garde le champ en optionnel pour compatibilité
    client = models.ForeignKey("dashboard.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="rewards")

    # Probabilité (catalogue)
    bucket = models.CharField(max_length=10, choices=BUCKET_CHOICES, default="SOUVENT")
    weight = models.PositiveIntegerField(default=1, help_text="Poids relatif dans sa catégorie")

    # Optionnels pour l’UX (conserve le design 'Min obtention / Délai')
    min_obtention = models.PositiveIntegerField(default=0, blank=True)
    cooldown_days = models.PositiveIntegerField(default=0, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.label
