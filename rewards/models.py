# rewards/models.py
from django.db import models
from accounts.models import Company
from dashboard.models import Client, Referral
import uuid
from django.urls import reverse

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

    # nom affiché (modifiable par l’admin)
    label = models.CharField(max_length=120, default="-10 % de remise")

    # délai choisi par l’admin en mois (1..6) + miroir en jours pour calculs
    cooldown_months = models.PositiveSmallIntegerField(default=1)
    cooldown_days = models.PositiveIntegerField(default=30)

    # NOUVEAU : nombre minimum de parrainages requis
    min_referrals_required = models.PositiveIntegerField(
        default=0,
        help_text="Nombre minimum de parrainages requis pour débloquer cette récompense."
    )

    # uniquement pour affichage (ex “80/100”), calculé ailleurs
    probability_display = models.CharField(max_length=20, default="", editable=False)

    class Meta:
        unique_together = (("company", "bucket"),)
        ordering = ("company", "bucket")

    def save(self, *args, **kwargs):
        # tient cooldown_days en phase avec cooldown_months
        self.cooldown_days = int(self.cooldown_months) * 30
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.company} • {self.get_bucket_display()} • {self.label}"


import secrets
from django.db import models
from django.utils import timezone
from django.urls import reverse


class Reward(models.Model):
    BUCKETS = (
        ("SOUVENT", "Souvent"),
        ("MOYEN", "Moyen"),
        ("RARE", "Rare"),
        ("TRES_RARE", "Très rare"),
    )
    STATE_CHOICES = (
        ("PENDING", "En attente"),
        ("SENT", "Envoyée"),
        ("DISABLED", "Désactivée"),
        ("ARCHIVED", "Archivée"),
    )

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="rewards")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="rewards")

    # NEW: relie la récompense à un parrainage précis (permet d'appliquer la règle « 1 par filleul »)
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

    # ---- Helpers ----
   
    def ensure_token(self, force: bool = False):
        if force or not self.token:
            self.token = secrets.token_urlsafe(24)                # <-- plus de token_urlsafe
        if not self.token_expires_at:
            self.token_expires_at = timezone.now() + timezone.timedelta(days=180)

    class Meta:
        indexes = [models.Index(fields=["company", "client", "state"])]
        # Empêche 2 rewards pour le même parrain ET le même referral (donc même filleul)
        constraints = [
            models.UniqueConstraint(
                fields=["company", "client", "referral"],
                name="uniq_reward_by_referrer_and_referral",
            )
        ]
        
    @property
    def claim_path(self) -> str:
        return reverse("rewards:use_reward", kwargs={"token": self.token}) if self.token else ""

    @property
    def claim_url(self) -> str:
        """
        Alias utilisé par les templates historiques.
        Retourne le chemin utilisable tel quel dans un <a href>.
        """
        return self.claim_path

    def __str__(self):
        return f"{self.label} ({self.get_bucket_display()})"