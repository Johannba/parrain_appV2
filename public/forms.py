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
