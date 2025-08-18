from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from .models import Client, Referral, Reward
# dashboard/views.py
from django import forms
from django.shortcuts import get_object_or_404, redirect


@login_required
def dashboard_root(request):
    u = request.user
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        return redirect("dashboard:superadmin_home")
    if hasattr(u, "is_admin_entreprise") and (u.is_admin_entreprise() or u.is_operateur()):
        return redirect("dashboard:company_home")
    # Client (V1 non utilisable) ou autre cas
    raise PermissionDenied("Accès réservé au personnel.")

@login_required
def superadmin_home(request):
    u = request.user
    if not (hasattr(u, "is_superadmin") and u.is_superadmin()):
        raise PermissionDenied("Réservé au Superadmin.")
    # TODO: brancher ici des stats globales si tu veux (context)
    context = {}
    return render(request, "dashboard/superadmin_home.html", context)

@login_required
def company_home(request):
    u = request.user
    if not (hasattr(u, "is_superadmin") and u.is_superadmin()) \
       and not (hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()) \
       and not (hasattr(u, "is_operateur") and u.is_operateur()):
        raise PermissionDenied("Réservé à l’Admin/Opérateur (ou Superadmin).")

    company = getattr(u, "company", None)
    context = {"company": company}
    return render(request, "dashboard/company_home.html", context)


def _require_company_staff(user):
    if hasattr(user, "is_superadmin") and user.is_superadmin():
        return
    if hasattr(user, "is_admin_entreprise") and user.is_admin_entreprise():
        return
    if hasattr(user, "is_operateur") and user.is_operateur():
        return
    raise PermissionDenied("Accès réservé au personnel de l’entreprise.")

# -------- Forms stylés ----------
class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("first_name", "last_name", "email", "phone", "is_referrer")
        labels = {
            "first_name": "Prénom",
            "last_name": "Nom",
            "email": "Email",
            "phone": "Téléphone",
            "is_referrer": "Est un parrain ?",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex : Alice"}),
            "last_name":  forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex : Martin"}),
            "email":      forms.EmailInput(attrs={"class": "form-control", "placeholder": "exemple@domaine.com"}),
            "phone":      forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex : 06 12 34 56 78"}),
            "is_referrer": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
class ReferralForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ("referrer", "referee", "status")
        labels = {
            "referrer": "Parrain",
            "referee": "Filleul",
            "status": "Statut",
        }
        widgets = {
            "referrer": forms.Select(attrs={"class": "form-select"}),
            "referee":  forms.Select(attrs={"class": "form-select"}),
            "status":   forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        company = kwargs.pop("company")
        super().__init__(*args, **kwargs)

        # Parrain = uniquement les clients marqués comme parrains
        self.fields["referrer"].queryset = Client.objects.filter(
            company=company, is_referrer=True
        )
        # Filleul = uniquement les clients NON parrains
        self.fields["referee"].queryset = Client.objects.filter(
            company=company, is_referrer=False
        )

        # Libellés lisibles
        fmt = lambda o: f"{o.last_name} {o.first_name} — {o.email or '—'}"
        self.fields["referrer"].label_from_instance = fmt
        self.fields["referee"].label_from_instance  = fmt

    def clean(self):
        cleaned = super().clean()
        referrer = cleaned.get("referrer")
        referee  = cleaned.get("referee")

        # Sécurité côté serveur (au cas où)
        if referrer and not referrer.is_referrer:
            self.add_error("referrer", "Le parrain doit être un client avec le statut « parrain ».")
        if referee and referee.is_referrer:
            self.add_error("referee", "Le filleul doit être un client non parrain.")
        if referrer and referee:
            if referrer.company_id != referee.company_id:
                self.add_error("referee", "Parrain et filleul doivent appartenir à la même entreprise.")
            if referrer.id == referee.id:
                self.add_error("referee", "Le parrain et le filleul doivent être différents.")
        return cleaned

# -------- Vues CRUD (Create) ----------
@login_required
def client_create(request):
    _require_company_staff(request.user)
    u = request.user
    # Superadmin peut choisir l’entreprise via ?company=ID, sinon prend celle du user
    company = getattr(u, "company", None)
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        from accounts.models import Company
        company_id = request.GET.get("company")
        if company_id:
            company = get_object_or_404(Company, pk=company_id)
    if company is None:
        raise PermissionDenied("Aucune entreprise associée.")

    if request.method == "POST":
        form = ClientForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = company
            obj.save()
            return redirect("dashboard:client_detail", pk=obj.pk)
    else:
        form = ClientForm()

    return render(request, "dashboard/client_form.html", {"form": form, "company": company})

@login_required
def referral_create(request):
    _require_company_staff(request.user)
    u = request.user
    # Contexte entreprise
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        from accounts.models import Company
        company_id = request.GET.get("company")
        if company_id:
            company = get_object_or_404(Company, pk=company_id)
        else:
            # fallback : si superadmin sans ?company, on interdit pour éviter de mélanger
            raise PermissionDenied("Superadmin : préciser ?company=<id> pour créer un parrainage.")
    else:
        company = u.company
        if company is None:
            raise PermissionDenied("Aucune entreprise associée.")

    if request.method == "POST":
        form = ReferralForm(request.POST, company=company)
        if form.is_valid():
            ref = form.save(commit=False)
            ref.company = company
            # Empêche parrain == filleul
            if ref.referrer_id == ref.referee_id:
                form.add_error("referee", "Le parrain et le filleul doivent être différents.")
            else:
                ref.save()
                return redirect("dashboard:client_detail", pk=ref.referrer_id)
    else:
        form = ReferralForm(company=company)

    return render(request, "dashboard/referral_form.html", {"form": form, "company": company})


@login_required
def clients_list(request):
    _require_company_staff(request.user)
    u = request.user
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        base_qs = Client.objects.all()
    else:
        base_qs = Client.objects.filter(company=u.company)

    t = (request.GET.get("type") or "tous").lower()
    if t == "parrains":
        qs = base_qs.filter(is_referrer=True)
    elif t == "filleuls":
        qs = base_qs.filter(is_referrer=False)
    else:
        qs = base_qs

    return render(request, "dashboard/clients_list.html", {
        "clients": qs, "filter_type": t
    })

# FICHE CLIENT (parrainés + où il est filleul)
@login_required
def client_detail(request, pk: int):
    _require_company_staff(request.user)
    u = request.user
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        client = get_object_or_404(Client.objects.select_related("company"), pk=pk)
    else:
        client = get_object_or_404(Client.objects.select_related("company"), pk=pk, company=u.company)

    # Parrainés par ce client (s'il est parrain)
    referrals_made = (Referral.objects
                      .select_related("referee")
                      .filter(company=client.company, referrer=client))
    # Cas où ce client est lui-même filleul d’un autre parrain
    referrals_received = (Referral.objects
                          .select_related("referrer")
                          .filter(company=client.company, referee=client))

    return render(request, "dashboard/client_detail.html", {
        "company": client.company,
        "client": client,
        "referrals_made": referrals_made,
        "referrals_received": referrals_received,
    })

@login_required
def reward_create(request, pk: int):
    _require_company_staff(request.user)
    u = request.user
    # sécurise l’accès au client
    if hasattr(u, "is_superadmin") and u.is_superadmin():
        client = get_object_or_404(Client, pk=pk)
    else:
        client = get_object_or_404(Client, pk=pk, company=u.company)

    if request.method == "POST":
        form = RewardForm(request.POST)
        if form.is_valid():
            reward = form.save(commit=False)
            reward.client = client
            reward.company = client.company
            reward.save()
            return redirect("dashboard:client_detail", pk=client.pk)
    else:
        form = RewardForm()

    return render(request, "dashboard/reward_form.html", {"form": form, "client": client})

