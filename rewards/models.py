# rewards/models.py
from datetime import timedelta
import secrets

from django.db import models
from django.utils import timezone
from django.urls import reverse

from accounts.models import Company
from dashboard.models import Client, Referral


class ProbabilityWheel(models.Model):
    """
    Roue (pool) cyclique par entreprise.
    - key   : identifie un tirage (ex: 'base_100', 'very_rare_10000')
    - pool  : liste ordonnée des résultats (ex: ['SOUVENT','SOUVENT',...,'NO_HIT'])
    - idx   : curseur de consommation
    - size  : longueur totale du pool (copie pour debug)
    """
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="probability_wheels"
    )
    key = models.SlugField(max_length=64)
    pool = models.JSONField(default=list)
    idx = models.PositiveIntegerField(default=0)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("company", "key"),)
        indexes = [models.Index(fields=["company", "key"])]

    def __str__(self):
        return f"{self.company} • {self.key} ({self.idx}/{self.size})"


class RewardTemplate(models.Model):
    BUCKETS = (
        ("SOUVENT", "Souvent"),
        ("MOYEN", "Moyen"),
        ("RARE", "Rare"),
        ("TRES_RARE", "Très rare"),
    )

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="reward_templates"
    )
    bucket = models.CharField(max_length=10, choices=BUCKETS)

    label = models.CharField(max_length=120, default="-10 % de remise")
    cooldown_months = models.PositiveSmallIntegerField(default=1)
    cooldown_days = models.PositiveIntegerField(default=30)

    # Seuil d’éligibilité
    min_referrals_required = models.PositiveIntegerField(
        default=0,
        help_text="Nombre minimum de parrainages requis pour débloquer cette récompense."
    )

    # Purement affichage (ex. '980/1000')
    probability_display = models.CharField(max_length=20, default="", editable=False)

    class Meta:
        unique_together = (("company", "bucket"),)
        ordering = ("company", "bucket")

    def save(self, *args, **kwargs):
        self.cooldown_days = int(self.cooldown_months) * 30
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company} • {self.get_bucket_display()} • {self.label}"


class Reward(models.Model):
    BUCKETS = (
        ("SOUVENT", "Souvent"),
        ("MOYEN", "Moyen"),
        ("RARE", "Rare"),
        ("TRES_RARE", "Très rare"),
    )
    STATE_CHOICES = (
        ("PENDING", "En attente"),
        ("SENT", "Distrubué"),
    )

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rewards")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="rewards")

    referral = models.ForeignKey(
        Referral, on_delete=models.CASCADE, related_name="rewards",
        null=True, blank=True
    )

    label = models.CharField(max_length=255)
    bucket = models.CharField(max_length=20, choices=BUCKETS)
    cooldown_days = models.PositiveIntegerField(default=0)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    token = models.CharField(max_length=64, unique=True, db_index=True, null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    redeemed_at = models.DateTimeField(null=True, blank=True)
    redeemed_channel = models.CharField(max_length=20, blank=True)

    class Meta:
        indexes = [models.Index(fields=["company", "client", "state"])]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "client", "referral"],
                name="uniq_reward_by_referrer_and_referral",
            )
        ]

    # ----------------- Helpers d’affichage -----------------

    def ensure_token(self, force: bool = False):
        if force or not self.token:
            self.token = secrets.token_urlsafe(24)
        if not self.token_expires_at:
            days = int(self.cooldown_days or 180)
            self.token_expires_at = timezone.now() + timedelta(days=days)

    @property
    def valid_until(self):
        if self.cooldown_days and self.created_at:
            return self.created_at + timedelta(days=int(self.cooldown_days))
        return None

    @property
    def cooldown_label(self) -> str:
        d = int(self.cooldown_days or 0)
        if d == 0:
            return "illimité"
        if d % 30 == 0:
            m = d // 30
            return f"{m} mois" if m > 1 else "1 mois"
        return f"{d} jours"

    def validity_sentence(self) -> str:
        if self.valid_until:
            return f"Validité : {self.cooldown_label} (jusqu’au {timezone.localtime(self.valid_until).strftime('%d/%m/%Y')})"
        return "Validité : illimité"

    @property
    def claim_path(self) -> str:
        return reverse("rewards:use_reward", kwargs={"token": self.token}) if self.token else ""

    @property
    def claim_url(self) -> str:
        return self.claim_path

    def __str__(self):
        return f"{self.label} ({self.get_bucket_display()})"
