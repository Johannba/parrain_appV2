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
            "referrer": forms.Select(attrs={"class": "form-select"}),
            "referee": forms.Select(attrs={"class": "form-select"}),
            "status":   forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.company = kwargs.pop("company", None)  # <-- on mémorise l’entreprise courante
        super().__init__(*args, **kwargs)

        user = getattr(self.request, "user", None)
        is_super = bool(user and hasattr(user, "is_superadmin") and user.is_superadmin())

        # Si superadmin et company non fournie, on montre tout (toutes entreprises)
        if is_super and self.company is None:
            self.fields["referrer"].queryset = (
                Client.objects.filter(is_referrer=True)
                .select_related("company")
                .order_by("last_name", "first_name")
            )
            self.fields["referee"].queryset = (
                Client.objects.filter(is_referrer=False)
                .select_related("company")
                .order_by("last_name", "first_name")
            )
        else:
            # Sinon on restreint à l’entreprise fournie (ou celle de l’utilisateur)
            comp = self.company or getattr(user, "company", None)
            self.fields["referrer"].queryset = (
                Client.objects.filter(company=comp, is_referrer=True)
                .order_by("last_name", "first_name")
            )
            self.fields["referee"].queryset = (
                Client.objects.filter(company=comp, is_referrer=False)
                .order_by("last_name", "first_name")
            )

        # Libellés ergonomiques dans le select
        def fmt(o):
            comp_name = o.company.name if o.company else "—"
            mail = o.email or "—"
            return f"{o.last_name} {o.first_name} — {mail} ({comp_name})"
        self.fields["referrer"].label_from_instance = fmt
        self.fields["referee"].label_from_instance  = fmt

    def clean(self):
        cleaned = super().clean()
        referrer = cleaned.get("referrer")
        referee  = cleaned.get("referee")

        # Règles de cohérence
        if referrer and not referrer.is_referrer:
            self.add_error("referrer", "Le parrain doit être un client marqué « parrain ».")
        if referee and referee.is_referrer:
            self.add_error("referee", "Le filleul doit être un client non parrain.")
        if referrer and referee:
            if referrer.company_id != referee.company_id:
                self.add_error("referee", "Parrain et filleul doivent appartenir à la même entreprise.")
            if referrer.id == referee.id:
                self.add_error("referee", "Parrain et filleul doivent être différents.")

        # Détection **doublon** : un filleul ne peut être parrainé qu'une fois par entreprise
        if referee:
            company = (
                self.company
                or getattr(getattr(self.request, "user", None), "company", None)
                or getattr(referee, "company", None)
            )

            if company and Referral.objects.filter(company=company, referee=referee).exists():
                # message clair, côté formulaire (l’unicité BD peut aussi lever une IntegrityError)
                self.add_error("referee", "Ce filleul a déjà un parrainage dans cette entreprise.")

        return cleaned
