# rewards/models.py
from django.db import models
from accounts.models import Company
from dashboard.models import Client


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
    """
    Les 4 récompenses FIXES par entreprise : seules les infos 'métier' (nom, délai)
    sont éditables ; les probabilités restent gérées ailleurs (roue/poids).
    """
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
    # nom affiché (modifiable par l’admin – ex “-10%”, “iPhone 16”, etc.)
    label = models.CharField(max_length=120, default="-10 % de remise")

    # délai choisi par l’admin en mois (1..6) + miroir en jours pour calculs
    cooldown_months = models.PositiveSmallIntegerField(default=1)
    cooldown_days = models.PositiveIntegerField(default=30)

    # uniquement pour affichage (ex “80/100”), calculé côté vue/service si tu préfères
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


class Reward(models.Model):
    """
    Récompense INSTANTIÉE pour un client (clonée depuis un template).
    """
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

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="rewards"
    )
    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="rewards"
    )

    # recopie du template au moment de l’attribution
    label = models.CharField(max_length=255)
    bucket = models.CharField(max_length=20, choices=BUCKETS)
    cooldown_days = models.PositiveIntegerField(default=0)

    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["company", "client", "state"])]

    def __str__(self):
        return f"{self.label} ({self.get_bucket_display()})"


