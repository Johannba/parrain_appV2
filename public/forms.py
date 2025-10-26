# public/forms.py
from django import forms
from django.core.exceptions import ValidationError
from dashboard.models import Client
from core.forms.fields import InternationalPhoneFormField


class ReferrerForm(forms.ModelForm):
    # téléphone obligatoire côté public
    phone = InternationalPhoneFormField(required=True)

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company  # injecté par la vue
        # champs requis
        self.fields["last_name"].required = True
        self.fields["first_name"].required = True
        self.fields["email"].required = True   # <- rendu obligatoire pour pouvoir envoyer un reset

    class Meta:
        model = Client
        fields = ["last_name", "first_name", "email", "phone"]
        widgets = {
            "last_name":  forms.TextInput(attrs={"placeholder": "Ex : Dupont", "class": "form-control"}),
            "first_name": forms.TextInput(attrs={"placeholder": "Ex : Marie",  "class": "form-control"}),
            "email":      forms.EmailInput(attrs={"placeholder": "Ex : marie@mail.com", "class": "form-control"}),
            # phone : géré par InternationalPhoneFormField
        }

    def clean(self):
        cleaned = super().clean()
        if not self.company:
            return cleaned

        last_name = (cleaned.get("last_name") or "").strip()
        first_name = (cleaned.get("first_name") or "").strip()
        if not last_name:
            # ta contrainte DB ne s’applique pas si last_name vide
            return cleaned

        # Réplique stricte de ta contrainte d’unicité (CI) pour les parrains
        exists = Client.objects.filter(
            company=self.company,
            is_referrer=True,
            last_name__iexact=last_name,
            first_name__iexact=first_name,
        ).exists()
        if exists:
            raise ValidationError("Un parrain portant ce nom existe déjà pour cette entreprise.")
        return cleaned


from django import forms
from django.core.exceptions import ValidationError
from dashboard.models import Client
from core.forms.fields import InternationalPhoneFormField

# ... (ReferrerForm inchangé) ...

class ReferrerResetForm(forms.ModelForm):
    """
    Formulaire de réinitialisation du PROFIL parrain existant.
    - On ne modifie PAS l'email (affiché en lecture seule).
    - On peut corriger nom, prénom, téléphone.
    - On évite les doublons de (nom, prénom) chez les parrains de l'entreprise.
    """
    phone = InternationalPhoneFormField(required=True)
    email_display = forms.EmailField(label="Email", disabled=True, required=False)

    class Meta:
        model = Client
        fields = ["last_name", "first_name", "phone"]  # email non éditable ici
        widgets = {
            "last_name":  forms.TextInput(attrs={"placeholder": "Ex : Dupont", "class": "form-control"}),
            "first_name": forms.TextInput(attrs={"placeholder": "Ex : Marie",  "class": "form-control"}),
            "phone":      forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, client: Client | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if client is not None:
            self.instance = client
        if self.instance and getattr(self.instance, "email", None):
            self.fields["email_display"].initial = self.instance.email

        # Champs requis
        self.fields["last_name"].required = True
        self.fields["first_name"].required = True

    def clean(self):
        cleaned = super().clean()
        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()

        # Empêcher de prendre un (nom, prénom) déjà utilisé par un AUTRE parrain de la même entreprise
        if self.instance and self.instance.company_id and ln:
            exists = Client.objects.filter(
                company_id=self.instance.company_id,
                is_referrer=True,
                last_name__iexact=ln,
                first_name__iexact=fn,
            ).exclude(pk=self.instance.pk).exists()
            if exists:
                self.add_error("last_name", "Un parrain portant ce nom existe déjà pour cette entreprise.")
        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        return cleaned
