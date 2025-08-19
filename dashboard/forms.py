from django import forms
from django.forms import TextInput, EmailInput, CheckboxInput, Select
from .models import Client, Referral, Company

class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("company", "last_name", "first_name", "email", "phone", "is_referrer")
        widgets = {
            "company": Select(attrs={"class": "form-select"}),
            "last_name": TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
            "first_name": TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
            "email": EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
            "phone": TextInput(attrs={"class": "form-control", "placeholder": "06 00 00 00 00"}),
            "is_referrer": CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        user = getattr(request, "user", None)
        is_super = hasattr(user, "is_superadmin") and user.is_superadmin()

        if is_super:
            self.fields["company"].queryset = Company.objects.order_by("name")
        else:
            # Admin/Opérateur → company forcée
            self.fields["company"].queryset = Company.objects.filter(pk=getattr(user.company, "pk", None))
            self.fields["company"].empty_label = None


class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ("referrer", "referee", "status")
        widgets = {
            "referrer": Select(attrs={"class": "form-select"}),
            "referee": Select(attrs={"class": "form-select"}),
            "status": Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        company = kwargs.pop("company", None)
        super().__init__(*args, **kwargs)

        user = getattr(request, "user", None)
        is_super = hasattr(user, "is_superadmin") and user.is_superadmin()

        if is_super and company is None:
            # Superadmin → toutes entreprises
            self.fields["referrer"].queryset = Client.objects.filter(is_referrer=True).select_related("company").order_by("last_name","first_name")
            self.fields["referee"].queryset  = Client.objects.filter(is_referrer=False).select_related("company").order_by("last_name","first_name")
        else:
            self.fields["referrer"].queryset = Client.objects.filter(company=company, is_referrer=True).order_by("last_name","first_name")
            self.fields["referee"].queryset  = Client.objects.filter(company=company, is_referrer=False).order_by("last_name","first_name")

        fmt = lambda o: f"{o.last_name} {o.first_name} — {o.email or '—'} ({o.company.name if o.company else '—'})"
        self.fields["referrer"].label_from_instance = fmt
        self.fields["referee"].label_from_instance  = fmt

    def clean(self):
        cleaned = super().clean()
        referrer = cleaned.get("referrer")
        referee  = cleaned.get("referee")

        if referrer and not referrer.is_referrer:
            self.add_error("referrer", "Le parrain doit être un client marqué « parrain ».")
        if referee and referee.is_referrer:
            self.add_error("referee", "Le filleul doit être un client non parrain.")
        if referrer and referee:
            if referrer.company_id != referee.company_id:
                self.add_error("referee", "Parrain et filleul doivent appartenir à la même entreprise.")
            if referrer.id == referee.id:
                self.add_error("referee", "Parrain et filleul doivent être différents.")
        return cleaned
