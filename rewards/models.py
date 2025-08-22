from django.db import models
from accounts.models import Company

class ProbabilityWheel(models.Model):
    """
    Roue (pool) cyclique, scopée par entreprise + par clé métier.
    - key: identifie un tirage (ex: 'base_100', 'very_rare_10000')
    - pool: liste ordonnée des résultats (ex: ['Souvent', 'NO_HIT', ...])
    - idx: curseur de consommation
    """
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="probability_wheels")
    key = models.SlugField(max_length=64)
    pool = models.JSONField(default=list)
    idx = models.PositiveIntegerField(default=0)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = (("company", "key"),)
        indexes = [models.Index(fields=["company", "key"])]

    def __str__(self):
        return f"{self.company} • {self.key} ({self.idx}/{self.size})"
