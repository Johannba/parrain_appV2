from django import forms
from django.forms import Select, TextInput, EmailInput
from .models import Client, Company, Referral

# --------------------------
# Utilitaire commun
# --------------------------
def _init_company_field(form, user):
    """Restreint le select 'company' selon le rôle."""
    is_super = bool(getattr(user, "is_superadmin", None) and user.is_superadmin())

    if is_super:
        form.fields["company"].queryset = Company.objects.order_by("name")
    else:
        # Admin / Opérateur : company forcée
        form.fields["company"].queryset = Company.objects.filter(
            pk=getattr(getattr(user, "company", None), "pk", None)
        )
        form.fields["company"].empty_label = None

from django import forms
from django.forms import TextInput, EmailInput, Select
from .models import Client, Company, Referral

# dashboard/forms.py
from django import forms
from django.forms import TextInput, EmailInput, Select
from .models import Client, Company, Referral


class ReferrerClientForm(forms.ModelForm):
    """
    Formulaire dédié à la création/édition d’un PARRAIN.
    - Ne montre pas is_referrer
    - Force is_referrer=True au save()
    - Superadmin voit toutes les entreprises, sinon company est forcée
    """
    class Meta:
        model = Client
        fields = ("company", "last_name", "first_name", "email", "phone")
        widgets = {
            "company": Select(attrs={"class": "form-select"}),
            "last_name": TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
            "first_name": TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
            "email": EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
            "phone": TextInput(attrs={"class": "form-control", "placeholder": "06 00 00 00 00"}),
        }

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        user = getattr(request, "user", None)
        is_super = bool(user and hasattr(user, "is_superadmin") and user.is_superadmin())

        if is_super:
            self.fields["company"].queryset = Company.objects.order_by("name")
        else:
            self.fields["company"].queryset = Company.objects.filter(
                pk=getattr(getattr(user, "company", None), "pk", None)
            )
            self.fields["company"].empty_label = None

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")
        email = (cleaned.get("email") or "").strip().lower()
        if company and email:
            exists = Client.objects.filter(
                company=company, email__iexact=email
            ).exclude(pk=self.instance.pk or 0).exists()
            if exists:
                self.add_error("email", "Un client avec cet email existe déjà dans cette entreprise.")
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.is_referrer = True
        if commit:
            obj.save()
        return obj


class RefereeClientForm(forms.ModelForm):
    """
    Formulaire dédié au FILLEUL (client non parrain).
    - Force is_referrer=False au save()
    - Même logique de restriction d’entreprise que ci-dessus
    """
    class Meta:
        model = Client
        fields = ("company", "last_name", "first_name", "email", "phone")
        widgets = {
            "company": Select(attrs={"class": "form-select"}),
            "last_name": TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
            "first_name": TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
            "email": EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
            "phone": TextInput(attrs={"class": "form-control", "placeholder": "06 00 00 00 00"}),
        }

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        user = getattr(request, "user", None)
        is_super = bool(user and hasattr(user, "is_superadmin") and user.is_superadmin())

        if is_super:
            self.fields["company"].queryset = Company.objects.order_by("name")
        else:
            self.fields["company"].queryset = Company.objects.filter(
                pk=getattr(getattr(user, "company", None), "pk", None)
            )
            self.fields["company"].empty_label = None

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")

        # Normalisation nom/prénom (trim + casse)
        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()

        # 1) Nom obligatoire pour un parrain
        if not ln:
            self.add_error("last_name", "Le nom est obligatoire pour créer un parrain.")

        # 2) Unicité nom/prénom dans l’entreprise (insensible à la casse)
        if company and ln:
            exists_name = Client.objects.filter(
                company=company,
                is_referrer=True,
                last_name__iexact=ln,
                first_name__iexact=fn,
            ).exclude(pk=self.instance.pk or 0).exists()
            if exists_name:
                self.add_error("last_name", "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.")

        # 3) (Optionnel) Unicité email dans l’entreprise si fourni
        if company and email:
            exists_email = Client.objects.filter(
                company=company, email__iexact=email
            ).exclude(pk=self.instance.pk or 0).exists()
            if exists_email:
                self.add_error("email", "Un client avec cet email existe déjà dans cette entreprise.")

        # Remet les valeurs normalisées
        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        cleaned["email"] = email
        return cleaned


class ReferralForm(forms.ModelForm):
    """
    Formulaire d’association Parrain → Filleul.
    ATTENTION : pas de champ 'status' car il n’existe pas dans le modèle (sinon FieldError).
    """
    class Meta:
        model = Referral
        fields = ("referrer", "referee")
        widgets = {
            "referrer": forms.Select(attrs={"class": "form-select"}),
            "referee": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        self.company = kwargs.pop("company", None)
        super().__init__(*args, **kwargs)

        user = getattr(self.request, "user", None)
        is_super = bool(user and hasattr(user, "is_superadmin") and user.is_superadmin())

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
            comp = self.company or getattr(user, "company", None)
            self.fields["referrer"].queryset = (
                Client.objects.filter(company=comp, is_referrer=True)
                .order_by("last_name", "first_name")
            )
            self.fields["referee"].queryset = (
                Client.objects.filter(company=comp, is_referrer=False)
                .order_by("last_name", "first_name")
            )

        def fmt(o):
            comp_name = o.company.name if o.company else "—"
            mail = o.email or "—"
            return f"{o.last_name} {o.first_name} — {mail} ({comp_name})"

        self.fields["referrer"].label_from_instance = fmt
        self.fields["referee"].label_from_instance = fmt

    def clean(self):
        cleaned = super().clean()
        referrer = cleaned.get("referrer")
        referee = cleaned.get("referee")

        if referrer and not referrer.is_referrer:
            self.add_error("referrer", "Le parrain doit être un client marqué « parrain ».")
        if referee and referee.is_referrer:
            self.add_error("referee", "Le filleul doit être un client non parrain.")
        if referrer and referee:
            if referrer.company_id != referee.company_id:
                self.add_error("referee", "Parrain et filleul doivent appartenir à la même entreprise.")
            if referrer.id == referee.id:
                self.add_error("referee", "Parrain et filleul doivent être différents.")

        if referee:
            company = (
                self.company
                or getattr(getattr(self.request, "user", None), "company", None)
                or getattr(referee, "company", None)
            )
            if company and Referral.objects.filter(company=company, referee=referee).exists():
                self.add_error("referee", "Ce filleul a déjà un parrainage dans cette entreprise.")
        return cleaned


# dashboard/forms.py (ajouter en bas du fichier)
from django import forms
from django.forms import TextInput, EmailInput
from .models import Client

class RefereeInlineForm(forms.ModelForm):
    """
    Form pour créer un FILLEUL (client non-parrain) sans champ 'company' (déduit du parrain).
    - is_referrer = False forcé au save
    - exige au moins un nom OU un email
    - évite le doublon d'email dans l'entreprise
    """
    class Meta:
        model = Client
        fields = ("last_name", "first_name", "email", "phone")
        widgets = {
            "last_name":  TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
            "first_name": TextInput(attrs={"class": "form-control", "placeholder": "Prénom"}),
            "email":      EmailInput(attrs={"class": "form-control", "placeholder": "email@exemple.com"}),
            "phone":      TextInput(attrs={"class": "form-control", "placeholder": "06 00 00 00 00"}),
        }

    def clean(self):
        cleaned = super().clean()
        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()

        if not ln and not email:
            self.add_error(None, "Renseignez au moins un nom ou un email pour le filleul.")

        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        cleaned["email"] = email
        return cleaned

    def save_with_company(self, company, commit=True):
        """Crée le filleul dans l’entreprise donnée, is_referrer=False."""
        obj = self.instance if self.instance and self.instance.pk else Client()
        obj.company = company
        obj.last_name = self.cleaned_data.get("last_name", "")
        obj.first_name = self.cleaned_data.get("first_name", "")
        obj.email = self.cleaned_data.get("email", None)
        obj.phone = self.cleaned_data.get("phone", "")
        obj.is_referrer = False
        if commit:
            obj.save()
        return obj
