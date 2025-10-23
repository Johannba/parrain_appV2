from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AuthenticationForm
from .models import User, Company
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Nom d’utilisateur",
        widget=forms.TextInput(attrs={
            "autocapitalize": "none",
            "autocorrect": "off",
            "spellcheck": "false",
            "autocomplete": "username",
            "inputmode": "text",
        })
    )
    password = forms.CharField(
        label="Mot de passe",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )

    def clean_username(self):
        return (self.cleaned_data.get("username") or "").strip()

from django import forms
from django.contrib.auth.forms import UserCreationForm
from accounts.models import User, Company  # adapte l'import si besoin

from django import forms
from django.contrib.auth.forms import UserCreationForm
from accounts.models import User, Company  # adapte l'import si besoin

from django import forms
from django.contrib.auth.forms import UserCreationForm
from accounts.models import User, Company  # adapte si besoin


class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "profile", "company")

    # ---------- Helpers ----------
    def _has_role(self, user, role_name: str) -> bool:
        if not user:
            return False
        maybe = getattr(user, f"is_{role_name}", None)
        if callable(maybe):
            try:
                return bool(maybe())
            except TypeError:
                pass
        flag = getattr(user, f"is_{role_name}", None)
        if isinstance(flag, bool):
            return flag
        return getattr(user, "profile", None) == role_name

    def _allowed_profiles_for(self, user):
        if not user or not user.is_authenticated:
            return ()
        if self._has_role(user, "superadmin"):
            return ("superadmin", "admin", "operateur")
        if self._has_role(user, "admin_entreprise"):
            return ("admin", "operateur")
        if self._has_role(user, "operateur"):
            return ("operateur",)
        return ()

    # ---------- Init ----------
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        u = getattr(self.request, "user", None)

        # Company selon créateur
        if u and u.is_authenticated:
            if self._has_role(u, "superadmin"):
                self.fields["company"].queryset = Company.objects.all()
            elif self._has_role(u, "admin_entreprise") or self._has_role(u, "operateur"):
                # Afficher le champ, mais bloqué sur l'entreprise de l'utilisateur
                self.fields["company"].queryset = Company.objects.filter(pk=u.company_id)
                self.fields["company"].initial = getattr(u, "company", None)
                self.fields["company"].disabled = True                     # <<< visible mais non modifiable
                self.fields["company"].help_text = "Fixé à votre entreprise."
            else:
                self.fields["company"].queryset = Company.objects.none()

        # 1) Retirer carrément le choix "superadmin" si le créateur n'est pas superadmin
        if not (u and self._has_role(u, "superadmin")):
            self.fields["profile"].choices = [
                (v, lbl) for (v, lbl) in self.fields["profile"].choices if v != "superadmin"
            ]

        # 2) Limiter aux rôles autorisés
        allowed = self._allowed_profiles_for(u)
        self.fields["profile"].choices = [
            (v, lbl) for (v, lbl) in self.fields["profile"].choices if v in allowed
        ]

    # ---------- Anti contournement ----------
    def clean_profile(self):
        value = self.cleaned_data.get("profile")
        u = getattr(self, "request", None).user if self.request else None
        if value not in self._allowed_profiles_for(u):
            raise forms.ValidationError("Vous n’êtes pas autorisé à créer ce type d’utilisateur.")
        return value

    # ---------- Cohérences métier ----------
    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get("profile")
        u = getattr(self, "request", None).user if self.request else None

        # Superadmin crée un Superadmin -> company vide
        if self._has_role(u, "superadmin") and profile == "superadmin":
            cleaned["company"] = None

        # Admin & Opérateur: forcer la company à la leur (au cas où le champ est disabled et donc non soumis)
        if self._has_role(u, "admin_entreprise") or self._has_role(u, "operateur"):
            if not u or not getattr(u, "company", None):
                self.add_error("company", "Vous devez être rattaché à une entreprise.")
            else:
                cleaned["company"] = u.company

        # Rappels de cohérence
        if profile in ("admin", "operateur") and not cleaned.get("company"):
            self.add_error("company", "L’Admin/Opérateur doit être rattaché à une entreprise.")
        if profile == "superadmin" and cleaned.get("company"):
            self.add_error("company", "Le Superadmin ne doit pas être rattaché à une entreprise.")

        return cleaned




class UserUpdateForm(UserChangeForm):
    # on réactive username et on ajoute des champs mot de passe "optionnels"
    password = None
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        widget=forms.PasswordInput,
        required=False,
        help_text="Laissez vide pour ne pas changer."
    )
    new_password2 = forms.CharField(
        label="Confirmer le nouveau mot de passe",
        widget=forms.PasswordInput,
        required=False,
    )

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "profile", "company", "is_active")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # (EXISTANT) Limitation du champ company
        if self.request and hasattr(self.request, "user"):
            u = self.request.user
            if getattr(u, "is_superadmin", lambda: False)():
                self.fields["company"].queryset = Company.objects.all()
            elif getattr(u, "is_admin_entreprise", lambda: False)():
                self.fields["company"].queryset = Company.objects.filter(pk=u.company_id)
            else:
                self.fields["company"].queryset = Company.objects.none()

        # (EXISTANT) Limiter les profils assignables par l’éditeur
        allowed = self._allowed_profiles_for(getattr(self.request, "user", None))
        self.fields["profile"].choices = [
            (v, lbl) for (v, lbl) in self.fields["profile"].choices if v in allowed
        ]

    # --- Rôles autorisés (inchangé) ---
    def _allowed_profiles_for(self, user):
        if not user or not user.is_authenticated:
            return ()
        if getattr(user, "is_superadmin", lambda: False)():
            return ("superadmin", "admin", "operateur")
        if getattr(user, "is_admin_entreprise", lambda: False)():
            return ("admin", "operateur")
        is_op_meth = getattr(user, "is_operateur", None)
        if callable(is_op_meth) and is_op_meth():
            return ("operateur",)
        if getattr(user, "profile", "") == "operateur":
            return ("operateur",)
        return ()

    # --- Username éditable : vérif unicité (hors instance courante) ---
    def clean_username(self):
        username = self.cleaned_data.get("username") or ""
        qs = User.objects.exclude(pk=self.instance.pk).filter(username__iexact=username)
        if qs.exists():
            raise ValidationError("Ce nom d’utilisateur est déjà utilisé.")
        return username

    # --- Règles rôles (anti-bypass) ---
    def clean_profile(self):
        value = self.cleaned_data.get("profile")
        u = getattr(self, "request", None).user if self.request else None
        if value not in self._allowed_profiles_for(u):
            raise forms.ValidationError("Affectation de profil non autorisée.")
        return value

    # --- Vérifs mot de passe & cohérence company/profil ---
    def clean(self):
        cleaned = super().clean()
        u = getattr(self, "request", None).user if self.request else None

        # Mot de passe : si l'un est rempli, on exige les deux + validation Django
        p1 = cleaned.get("new_password1") or ""
        p2 = cleaned.get("new_password2") or ""
        if p1 or p2:
            if p1 != p2:
                self.add_error("new_password2", "Les mots de passe ne correspondent pas.")
            else:
                # validation selon les validators Django (longueur, complexité, etc.)
                try:
                    password_validation.validate_password(p1, user=self.instance)
                except ValidationError as e:
                    self.add_error("new_password1", e)

        # Règles company selon l'éditeur
        is_admin = getattr(u, "is_admin_entreprise", lambda: False)()
        is_op = (callable(getattr(u, "is_operateur", None)) and u.is_operateur()) or getattr(u, "profile", "") == "operateur"
        if is_admin or is_op:
            cleaned["company"] = u.company

        # Si on bascule la cible vers superadmin -> company=None
        if cleaned.get("profile") == "superadmin":
            cleaned["company"] = None

        return cleaned

    # --- Application des changements username + password ---
    def save(self, commit=True):
        user = super().save(commit=False)

        # username déjà passé par clean_username
        user.username = self.cleaned_data.get("username", user.username)

        # appliquer le nouveau mot de passe si fourni
        p1 = self.cleaned_data.get("new_password1")
        if p1:
            user.set_password(p1)

        if commit:
            user.save()
            # Si tu gères groups/perms/relations M2M ailleurs, appelle self.save_m2m()
            self.save_m2m()
        return user
