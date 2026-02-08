from django import forms
from django.forms import Select, TextInput, EmailInput
from .models import Client, Company, Referral

# --- Normalisation téléphone (sans jamais forcer +33) ---
try:
    import phonenumbers
except Exception:
    phonenumbers = None  # dégrade en no-op si lib absente

# Préfixes DOM/TOM -> régions libphonenumber
FR_DOM_PREFIX_MAP = {
    "0590": "GP", "0690": "GP",  # Guadeloupe (+590)
    "0594": "GF", "0694": "GF",  # Guyane (+594)
    "0596": "MQ", "0696": "MQ",  # Martinique (+596)
    "0262": "RE", "0692": "RE", "0693": "RE",  # Réunion (+262)
    "0269": "YT", "0691": "YT",  # Mayotte (+262)
}

def _company_region_hint(company) -> str | None:
    """Essaye de déduire l'ISO2 (GP, GF, MQ, RE, YT, FR, ...) depuis l'objet company."""
    if not company:
        return None
    # attributs possibles selon tes modèles
    for attr in ("country_code", "iso2", "country", "pays"):
        val = getattr(company, attr, None)
        if not val:
            continue
        code = str(val).strip().upper()
        name_to_iso2 = {
            "GUADELOUPE": "GP", "GP": "GP",
            "MARTINIQUE": "MQ", "MQ": "MQ",
            "GUYANE": "GF", "GUYANE FRANCAISE": "GF", "GUYANE FRANÇAISE": "GF", "GF": "GF",
            "REUNION": "RE", "RÉUNION": "RE", "RE": "RE",
            "MAYOTTE": "YT", "YT": "YT",
            "SAINT-PIERRE-ET-MIQUELON": "PM", "PM": "PM",
            "NOUVELLE-CALEDONIE": "NC", "NOUVELLE-CALÉDONIE": "NC", "NC": "NC",
            "POLYNESIE FRANCAISE": "PF", "POLYNÉSIE FRANÇAISE": "PF", "PF": "PF",
            "FRANCE": "FR", "FR": "FR",
        }
        if code in name_to_iso2:
            return name_to_iso2[code]
        if len(code) == 2:  # déjà un ISO2
            return code
    return None

# --- Remplace intégralement cette fonction ---
def _guess_region_from_number(raw: str) -> str | None:
    """
    Déduit une région depuis la forme du numéro (prioritaire sur company).
    - DOM/TOM (0590/0594/0596/0262/0269/06xx DOM) -> GP/GF/MQ/RE/YT
    - France métropolitaine : 10 chiffres commençant par 0 -> FR
    - Sinon : None
    """
    s = "".join(ch for ch in str(raw) if ch.isdigit() or ch == "+")
    if s.startswith("+"):
        return None  # déjà international

    # DOM/TOM d'abord
    for p, region in FR_DOM_PREFIX_MAP.items():
        if s.startswith(p):
            return region

    # France métropolitaine (fix) : 0 + 9 chiffres
    if len(s) == 10 and s.startswith("0") and s[1].isdigit():
        return "FR"

    return None


def normalize_phone(raw: str, company=None) -> str:
    """
    Retourne un téléphone **uniformisé**.
    - Si commence par '+', validation + E.164.
    - Sinon, essaie region depuis company, DOM, puis motif FR (10 chiffres début '0').
    - Si impossible/ambigu : on renvoie tel quel (pas de +33 forcé à l'aveugle).
    """
    raw = (raw or "").strip()
    if not raw or phonenumbers is None:
        return raw

    if raw.startswith("+"):
        try:
            n = phonenumbers.parse(raw, None)
            return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            return raw

    region = _company_region_hint(company) or _guess_region_from_number(raw)
    if not region:
        return raw

    try:
        n = phonenumbers.parse(raw, region)
        if not phonenumbers.is_valid_number(n):
            return raw
        return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return raw

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

        # stockage interne pour "upsert"
        self._existing_client = None

    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")

        # Normalisation douce
        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()
        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        cleaned["email"] = email
        
         # ✅ Normalisation téléphone SANS +33 forcé
        phone = (cleaned.get("phone") or "").strip()
        cleaned["phone"] = normalize_phone(phone, company)

        # 1) Si un PARRAIN existe déjà avec même email → erreur
        if company and email:
            existing_parrain_same_email = Client.objects.filter(
                company=company, email__iexact=email, is_referrer=True
            ).exclude(pk=self.instance.pk or 0).exists()
            if existing_parrain_same_email:
                self.add_error("email", "Un parrain avec cet email existe déjà dans cette entreprise.")
                return cleaned

        # 2) Sinon on cherche un client existant à RÉUTILISER (email prioritaire)
        existing = None
        if company and email:
            existing = Client.objects.filter(
                company=company, email__iexact=email
            ).exclude(pk=self.instance.pk or 0).first()

        # 3) À défaut d’email, tentative par (nom, prénom) si fournis
        if not existing and company and ln:
            existing = Client.objects.filter(
                company=company, last_name__iexact=ln, first_name__iexact=fn
            ).exclude(pk=self.instance.pk or 0).first()

        self._existing_client = existing  # pourra être None
        return cleaned

    def save(self, commit=True):
        """
        UP SERT :
        - Si un client existe déjà (même entreprise par email ou par nom/prénom),
          on le promeut en parrain + on met à jour ses champs.
        - Sinon on crée un nouveau client en parrain.
        """
        data = self.cleaned_data
        company = data.get("company")

        obj = self._existing_client or self.instance
        if not getattr(obj, "pk", None):
            obj = Client()

        # Remplit / met à jour
        obj.company = company
        obj.last_name = data.get("last_name", "") or obj.last_name
        obj.first_name = data.get("first_name", "") or obj.first_name
        obj.email = data.get("email") or obj.email
        obj.phone = data.get("phone", "") or obj.phone
        obj.is_referrer = True  # ✅ promotion en parrain

        if commit:
            obj.save()
        return obj



class RefereeClientForm(forms.ModelForm):
    """
    Formulaire dédié au FILLEUL (client non parrain).
    - Force is_referrer=False au save()
    - Même logique de restriction d’entreprise que ci-dessus
    """
    def clean(self):
        cleaned = super().clean()
        company = cleaned.get("company")

        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()
        phone = (cleaned.get("phone") or "").strip()
        
          # ✨ Normalisation pour uniformiser avec le public et le parrain
        cleaned["phone"] = normalize_phone(phone, company)

        # libellé neutre (pas "parrain")
        if not ln and not email:
            self.add_error("last_name", "Le nom est obligatoire (ou renseignez un email).")

        if company and email:
            exists_email = Client.objects.filter(
                company=company, email__iexact=email
            ).exclude(pk=self.instance.pk or 0).exists()
            if exists_email:
                self.add_error("email", "Un client avec cet email existe déjà dans cette entreprise.")

        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        cleaned["email"] = email
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.is_referrer = False  # ✅ filleul
        if commit:
            obj.save()
        return obj


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
        
        raw_phone = self.cleaned_data.get("phone", "")
        obj.phone = normalize_phone(raw_phone, company)
        
        obj.is_referrer = False
        
        if commit:
            obj.save()
        return obj

from django import forms
from django.forms import TextInput, EmailInput
from dashboard.models import Client  # ou .models selon ton app
from dashboard.forms import normalize_phone  # si tu veux factoriser, sinon importe la fonction

# public/forms.py
from django import forms
from django.forms import TextInput, EmailInput
from dashboard.models import Client
from dashboard.forms import normalize_phone  # garde ta fonction existante


class ReferrerPublicForm(forms.ModelForm):
    """
    Form PUBLIC: inscription parrain depuis landing.
    - company injectée via __init__(company=...)
    - is_referrer=True forcé au save()
    - contrôles doublons : email + (nom, prénom)
    """
    class Meta:
        model = Client
        fields = ("first_name", "last_name", "email", "phone")
        widgets = {
            "first_name": TextInput(attrs={"placeholder": "Prénom"}),
            "last_name":  TextInput(attrs={"placeholder": "Nom"}),
            "email":      EmailInput(attrs={"placeholder": "Email"}),
            "phone":      TextInput(attrs={"placeholder": "Numéro de téléphone"}),
        }

    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop("company", None)
        super().__init__(*args, **kwargs)

        # Optionnel : enlever les classes bootstrap pour laisser ton CSS modale gérer
        for f in self.fields.values():
            f.widget.attrs.pop("class", None)

        # champs requis
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        self.fields["email"].required = True
        self.fields["phone"].required = True

    def clean(self):
        cleaned = super().clean()
        company = self.company

        if not company:
            raise forms.ValidationError("Entreprise manquante.")

        ln = (cleaned.get("last_name") or "").strip()
        fn = (cleaned.get("first_name") or "").strip()
        email = (cleaned.get("email") or "").strip().lower()
        phone = (cleaned.get("phone") or "").strip()

        cleaned["last_name"] = ln
        cleaned["first_name"] = fn
        cleaned["email"] = email
        cleaned["phone"] = normalize_phone(phone, company)

        # ✅ email déjà utilisé par un parrain dans cette entreprise
        if email and Client.objects.filter(
            company=company, email__iexact=email, is_referrer=True
        ).exists():
            self.add_error("email", "Cet email est déjà utilisé par un parrain de cette entreprise.")

        # ✅ doublon (nom, prénom) chez les parrains de l’entreprise (CI)
        # -> évite l'IntegrityError sur uniq_referrer_name_per_company_ci
        if ln and Client.objects.filter(
            company=company,
            is_referrer=True,
            last_name__iexact=ln,
            first_name__iexact=fn,
        ).exists():
            self.add_error("last_name", "Un parrain portant ce nom existe déjà pour cette entreprise.")

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.company = self.company
        obj.is_referrer = True
        if commit:
            obj.save()
        return obj
