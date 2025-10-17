from django.contrib.auth.models import AbstractUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify

# accounts/models.py
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db.models.functions import Lower


hex_color_validator = RegexValidator(
    regex=r"^#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$",
    message="Couleur hex attendue, ex. #ec4899 ou #000",
)

class Company(models.Model):
    name = models.CharField(max_length=150, unique=True)
    # Rendez le slug "blank=True" pour pouvoir le laisser vide en admin et le laisser s'auto-remplir
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    is_active = models.BooleanField(default=True)

    # --- Nouveaux champs (branding / présentation publique) ---
    slogan = models.CharField(max_length=255, blank=True)
    primary_color = models.CharField(
        max_length=7, default="#ec4899", validators=[hex_color_validator]
    )
    secondary_color = models.CharField(
        max_length=7, default="#000000", validators=[hex_color_validator]
    )
    logo = models.ImageField(upload_to="company_logos/", blank=True, null=True)
    # (facultatif) domaine dédié si un jour tu veux multi-domaine :
    # domain = models.CharField(max_length=255, blank=True, unique=True)

    def _build_unique_slug(self):
        base = slugify(self.name or "")
        slug = base or "entreprise"
        i = 1
        while Company.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            i += 1
            slug = f"{base}-{i}"
        return slug

    def save(self, *args, **kwargs):
        # Auto-complète le slug s'il est vide (création ou slug effacé volontairement)
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprises"

    def __str__(self):
        return self.name

class UserManager(DjangoUserManager):
    """Ajoute la gestion du champ 'profile' lors de la création."""

    def create_user(self, username, email=None, password=None, **extra_fields):
        # Par défaut, un utilisateur "normal" = CLIENT (comme aujourd'hui)
        extra_fields.setdefault("profile", User.Profile.CLIENT)
        return super().create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        # Force les flags Django + rôle métier Superadmin + pas d'entreprise
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        extra_fields["profile"] = User.Profile.SUPERADMIN
        extra_fields["company"] = None
        # Laisse Django faire ses vérifs (is_staff/is_superuser) et créer l’utilisateur
        return super().create_superuser(username, email, password, **extra_fields)


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
    objects = UserManager() 
    # Contrainte business simple (optionnelle)
    def clean(self):
        from django.core.exceptions import ValidationError
        if self.profile == self.Profile.SUPERADMIN and self.company:
            raise ValidationError(_("Un superadmin ne doit pas être rattaché à une entreprise."))

    def is_superadmin(self) -> bool:
    # Superadmin métier OU superuser Django
        return self.is_superuser or self.profile == self.Profile.SUPERADMIN

    def is_admin_entreprise(self) -> bool:
        return self.profile == self.Profile.ADMIN

    def is_operateur(self) -> bool:
        return self.profile == self.Profile.OPERATEUR

    def __str__(self):
        return f"{self.username} • {self.get_profile_display()}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("username"),
                name="unique_username_ci",
            ),
        ]