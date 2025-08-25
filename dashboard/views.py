# dashboard/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts.models import Company
from dashboard.models import Client, Referral
from .forms import ClientForm, ReferralForm
from rewards.models import Reward
from rewards.forms import RewardTemplateForm

# Tirage de récompense
from rewards.services.probabilities import (
    tirer_recompense, SOUVENT, MOYEN, RARE, TRES_RARE
)


# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def _is_superadmin(u) -> bool:
    return hasattr(u, "is_superadmin") and u.is_superadmin()


def _is_company_admin(u) -> bool:
    return hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()


def _is_operator(u) -> bool:
    return hasattr(u, "is_operateur") and u.is_operateur()


def _require_company_staff(user):
    if _is_superadmin(user) or _is_company_admin(user) or _is_operator(user):
        return
    raise PermissionDenied("Accès réservé au personnel.")


def _company_for(user):
    # Admin d’entreprise / Opérateur → sa company
    # Superadmin → doit choisir une entreprise (à adapter si tu as un sélecteur global)
    return getattr(user, "company", None)


# -------------------------------------------------------------
# Redirections d’accueil selon le rôle
# -------------------------------------------------------------
@login_required
def dashboard_root(request):
    u = request.user
    if _is_superadmin(u):
        return redirect("dashboard:superadmin_home")
    if _is_company_admin(u) or _is_operator(u):
        return redirect("dashboard:company_home")
    raise PermissionDenied("Accès réservé au personnel.")


@login_required
def superadmin_home(request):
    if not _is_superadmin(request.user):
        raise PermissionDenied("Réservé au Superadmin.")
    return render(request, "dashboard/superadmin_home.html", {})


@login_required
def company_home(request):
    u = request.user
    if not (_is_superadmin(u) or _is_company_admin(u) or _is_operator(u)):
        raise PermissionDenied("Réservé à l’Admin/Opérateur (ou Superadmin).")
    company = _company_for(u)
    return render(request, "dashboard/company_home.html", {"company": company})


# -------------------------------------------------------------
# Clients : création / liste / fiche / édition / suppression
# -------------------------------------------------------------
@login_required
def client_create(request):
    _require_company_staff(request.user)

    if request.method == "POST":
        form = ClientForm(request.POST, request=request)
        if form.is_valid():
            obj = form.save(commit=False)
            if not _is_superadmin(request.user):
                # sécurité multi-entreprise
                obj.company = request.user.company
            obj.save()
            messages.success(request, "Client créé.")
            return redirect("dashboard:clients_list")
    else:
        form = ClientForm(request=request)

    return render(request, "dashboard/client_form.html", {"form": form})


@login_required
def clients_list(request):
    _require_company_staff(request.user)

    u = request.user
    base_qs = Client.objects.all() if _is_superadmin(u) else Client.objects.filter(company=u.company)

    # Filtre par type
    t = (request.GET.get("type") or "tous").lower()
    if t == "parrains":
        qs = base_qs.filter(is_referrer=True)
    elif t == "filleuls":
        qs = base_qs.filter(is_referrer=False)
    else:
        qs = base_qs

    # Recherche plein-texte
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(email__icontains=q)
        )

    qs = qs.order_by("last_name", "first_name")

    return render(request, "dashboard/clients_list.html", {
        "clients": qs,
        "filter_type": t,
        "current_q": q,
    })


@login_required
def client_detail(request, pk: int):
    _require_company_staff(request.user)

    u = request.user
    if _is_superadmin(u):
        client = get_object_or_404(Client.objects.select_related("company"), pk=pk)
    else:
        client = get_object_or_404(Client.objects.select_related("company"), pk=pk, company=u.company)

    # Historique des parrainages (où le client est impliqué)
    history_qs = (
        Referral.objects
        .select_related("referrer", "referee")
        .filter(company=client.company)
        .filter(Q(referrer=client) | Q(referee=client))
        .order_by("-created_at", "-id")
    )
    history_page = Paginator(history_qs, 8).get_page(request.GET.get("h"))

    # Récompenses par statut
    rewards_ok      = Reward.objects.filter(company=client.company, client=client, state="SENT").order_by("-id")
    rewards_pending = Reward.objects.filter(company=client.company, client=client, state="PENDING").order_by("-id")
    rewards_unused  = Reward.objects.filter(company=client.company, client=client, state="DISABLED").order_by("-id")

    # KPIs
    kpi_obtenus  = rewards_ok.count()
    kpi_attente  = rewards_pending.count()
    kpi_nonutils = rewards_unused.count()

    # Pagination des 3 blocs
    p_ok      = Paginator(rewards_ok, 5)
    p_pending = Paginator(rewards_pending, 5)
    p_unused  = Paginator(rewards_unused, 5)

    return render(request, "dashboard/client_detail.html", {
        "company": client.company,
        "client": client,
        "history_page": history_page,
        "page_ok": p_ok.get_page(request.GET.get("ok")),
        "page_pending": p_pending.get_page(request.GET.get("pending")),
        "page_unused": p_unused.get_page(request.GET.get("unused")),
        "kpi_obtenus": kpi_obtenus,
        "kpi_attente": kpi_attente,
        "kpi_nonutils": kpi_nonutils,
    })


@login_required
def client_update(request, pk):
    _require_company_staff(request.user)

    obj = get_object_or_404(Client, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    if request.method == "POST":
        form = ClientForm(request.POST, instance=obj, request=request)
        if form.is_valid():
            c = form.save(commit=False)
            if not _is_superadmin(request.user):
                c.company = request.user.company
            c.save()
            messages.success(request, "Client mis à jour.")
            return redirect("dashboard:clients_list")
    else:
        form = ClientForm(instance=obj, request=request)

    return render(request, "dashboard/client_form.html", {"form": form})


@login_required
def client_delete(request, pk):
    _require_company_staff(request.user)

    obj = get_object_or_404(Client, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Client supprimé.")
        return redirect("dashboard:clients_list")

    return render(request, "dashboard/confirm_delete.html", {
        "title": "Supprimer le client",
        "message": f"Supprimer définitivement {obj.last_name} {obj.first_name} ?",
        "back_url": "dashboard:clients_list",
    })


# -------------------------------------------------------------
# Parrainages : création / édition / suppression
# -------------------------------------------------------------
@login_required
def referral_create(request):
    _require_company_staff(request.user)

    u = request.user
    is_super = _is_superadmin(u)

    # Entreprise courante pour le formulaire
    current_company = None
    if not is_super:
        current_company = _company_for(u)
    else:
        cid = request.GET.get("company")
        if cid:
            current_company = get_object_or_404(Company, pk=cid)

    if request.method == "POST":
        form = ReferralForm(request.POST, request=request, company=current_company)
        if form.is_valid():
            referral = form.save(commit=False)
            referral.company = current_company or getattr(referral.referrer, "company", None)

            try:
                referral.save()
            except IntegrityError:
                form.add_error("referee", "Ce filleul a déjà un parrainage dans cette entreprise.")
            else:
                messages.success(request, "Parrainage créé.")
                return redirect("dashboard:clients_list")
    else:
        form = ReferralForm(request=request, company=current_company)

    return render(request, "dashboard/referral_form.html", {"form": form})


@login_required
def referral_update(request, pk):
    _require_company_staff(request.user)

    obj = get_object_or_404(Referral, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    current_company = None if _is_superadmin(request.user) else request.user.company

    if request.method == "POST":
        form = ReferralForm(request.POST, instance=obj, request=request, company=current_company)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = r.referrer.company  # cohérence
            r.save()
            messages.success(request, "Parrainage mis à jour.")
            return redirect("dashboard:referrals_list")
    else:
        form = ReferralForm(instance=obj, request=request, company=current_company)

    return render(request, "dashboard/referral_form.html", {"form": form})


@login_required
def referral_delete(request, pk):
    _require_company_staff(request.user)

    obj = get_object_or_404(Referral, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Parrainage supprimé.")
        return redirect("dashboard:referrals_list")

    return render(request, "dashboard/confirm_delete.html", {
        "title": "Supprimer le parrainage",
        "message": "Confirmer la suppression de ce parrainage ?",
        "back_url": "dashboard:referrals_list",
    })


# -------------------------------------------------------------
# Récompenses : création simple (manuel) & tirage automatique
# -------------------------------------------------------------
@login_required
def reward_create(request, pk: int):
    """
    Création manuelle d’une Reward pour un client.
    """
    _require_company_staff(request.user)

    u = request.user
    client = get_object_or_404(
        Client,
        pk=pk,
        **({} if _is_superadmin(u) else {"company": u.company})
    )

    if request.method == "POST":
        form = RewardTemplateForm(request.POST)
        if form.is_valid():
            reward = form.save(commit=False)
            reward.client = client
            reward.company = client.company
            reward.save()
            messages.success(request, "Récompense créée.")
            return redirect("dashboard:client_detail", pk=client.pk)
    else:
        form = RewardTemplateForm()

    return render(request, "dashboard/reward_form.html", {"form": form, "client": client})


@login_required
@transaction.atomic
def validate_referral_and_award(request, referral_id: int):
    """
    Valide un parrainage ET effectue 1 tirage sur la roue de proba de l’entreprise.
    Crée une Reward alignée sur le token tiré. (Cadeau attribué au filleul)
    """
    _require_company_staff(request.user)

    referral = get_object_or_404(
        Referral.objects.select_related("referee", "referrer", "company"),
        pk=referral_id
    )

    # Sécurité multi‑entreprises
    user_company = _company_for(request.user)
    if user_company and referral.company_id != user_company.id and not _is_superadmin(request.user):
        messages.error(request, "Ce parrainage n’appartient pas à votre entreprise.")
        return redirect(reverse("dashboard:referrals_list"))

    # Bénéficiaire : le filleul (adapter si tu préfères le parrain)
    client: Client = referral.referee

    # Tirage EXACT via la roue de la company
    token = tirer_recompense(referral.company)

    LABELS = {
        SOUVENT:   "Récompense Souvent",
        MOYEN:     "Récompense Moyen",
        RARE:      "Récompense Rare",
        TRES_RARE: "Récompense Très rare",
    }
    STATE = "PENDING"  # "SENT" si envoi instantané

    reward = Reward.objects.create(
        company=referral.company,
        client=client,
        label=LABELS.get(token, "Récompense"),
        code="",
        channel="email",
        state=STATE,
    )

    messages.success(
        request,
        f"Parrainage validé. Tirage : {token.replace('_',' ').title()} • "
        f"Récompense #{reward.pk} créée pour {client}."
    )
    # Tu peux aussi rediriger vers la fiche client :
    # return redirect("dashboard:client_detail", pk=client.pk)
    return redirect(reverse("rewards:list"))
