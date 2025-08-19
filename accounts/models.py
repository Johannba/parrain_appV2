from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify

class Company(models.Model):
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=160, unique=True)
    is_active = models.BooleanField(default=True)
    
    def _build_unique_slug(self):
        base = slugify(self.name or "")
        slug = base or "entreprise"
        i = 1
        # Évite les collisions (ex: chrono-pizza, chrono-pizza-1, etc.)
        while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            i += 1
            slug = f"{base}-{i}"
        return slug

    def save(self, *args, **kwargs):
        # Remplit le slug uniquement s'il est vide (création ou si on l'efface volontairement)
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"

    def __str__(self):
        return self.name


class User(AbstractUser, PermissionsMixin):
    class Profile(models.TextChoices):
        SUPERADMIN = "superadmin", "Superadmin (plateforme)"
        ADMIN = "admin", "Admin d’entreprise"
        OPERATEUR = "operateur", "Opérateur"
        CLIENT = "client", "Client (V1: non utilisable)"

    # Rôle
    profile = models.CharField(
        max_length=20,
        choices=Profile.choices,
        default=Profile.CLIENT,
    )

    # Rattachement éventuel à une entreprise (pas de company pour superadmin)
    company = models.ForeignKey(
        Company, on_delete=models.SET_NULL, null=True, blank=True, related_name="users"
    )

    # Contrainte business simple (optionnelle)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.profile == self.Profile.SUPERADMIN and self.company:
            raise ValidationError(_("Un superadmin ne doit pas être rattaché à une entreprise."))

    def is_superadmin(self) -> bool:
        return self.profile == self.Profile.SUPERADMIN

    def is_admin_entreprise(self) -> bool:
        return self.profile == self.Profile.ADMIN

    def is_operateur(self) -> bool:
        return self.profile == self.Profile.OPERATEUR

    def __str__(self):
        return f"{self.username} • {self.get_profile_display()}"
