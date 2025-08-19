from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from .models import Client, Referral

from django.db import IntegrityError
from accounts.models import Company
# dashboard/views.py

from .forms import ClientForm, ReferralForm
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
    if getattr(user, "is_superadmin", lambda: False)():
        return
    if getattr(user, "is_admin_entreprise", lambda: False)():
        return
    if getattr(user, "is_operateur", lambda: False)():
        return
    raise PermissionDenied


@login_required
def client_create(request):
    _require_company_staff(request.user)
    if request.method == "POST":
        form = ClientForm(request.POST, request=request)
        if form.is_valid():
            obj = form.save(commit=False)
            if not getattr(request.user, "is_superadmin", lambda: False)():
                obj.company = request.user.company  # sécurité
            obj.save()
            return redirect("dashboard:clients_list")
    else:
        form = ClientForm(request=request)
    return render(request, "dashboard/client_form.html", {"form": form})



@login_required
def referral_create(request):
    _require_company_staff(request.user)

    u = request.user
    is_super = getattr(u, "is_superadmin", lambda: False)()

    # Entreprise courante pour le formulaire :
    # - Admin/Opérateur : sa propre company
    # - Superadmin : facultatif via ?company=<id> (sinon on prendra celle du parrain au moment du save)
    current_company = None
    if not is_super:
        current_company = getattr(u, "company", None)
    else:
        cid = request.GET.get("company")
        if cid:
            current_company = get_object_or_404(Company, pk=cid)

    if request.method == "POST":
        form = ReferralForm(request.POST, request=request, company=current_company)
        if form.is_valid():
            referral = form.save(commit=False)

            # Company cohérente (sécurité) :
            # - si superadmin sans company explicite -> on dérive de referrer
            # - sinon on force toujours la company cohérente
            referral.company = current_company or getattr(referral.referrer, "company", None)

            try:
                referral.save()
            except IntegrityError:
                # Protège contre la contrainte d’unicité (company, referee) en base
                form.add_error("referee", "Ce filleul a déjà un parrainage dans cette entreprise.")
            else:
                messages.success(request, "Parrainage créé.")
                return redirect("dashboard:clients_list")
    else:
        form = ReferralForm(request=request, company=current_company)

    return render(request, "dashboard/referral_form.html", {"form": form})



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


# ---------- Clients ----------
@login_required
def client_update(request, pk):
    _require_company_staff(request.user)
    obj = get_object_or_404(Client, pk=pk)
    if not request.user.is_superadmin() and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")
    if request.method == "POST":
        form = ClientForm(request.POST, instance=obj, request=request)
        if form.is_valid():
            c = form.save(commit=False)
            if not request.user.is_superadmin():
                c.company = request.user.company
            c.save()
            return redirect("dashboard:clients_list")
    else:
        form = ClientForm(instance=obj, request=request)
    return render(request, "dashboard/client_form.html", {"form": form})

@login_required
def client_delete(request, pk):
    _require_company_staff(request.user)
    obj = get_object_or_404(Client, pk=pk)
    if not request.user.is_superadmin() and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")
    if request.method == "POST":
        obj.delete()
        return redirect("dashboard:clients_list")
    return render(request, "dashboard/confirm_delete.html", {
        "title": "Supprimer le client",
        "message": f"Supprimer définitivement {obj.last_name} {obj.first_name} ?",
        "back_url": "dashboard:clients_list",
    })

# ---------- Parrainages ----------
@login_required
def referral_update(request, pk):
    _require_company_staff(request.user)
    obj = get_object_or_404(Referral, pk=pk)
    if not request.user.is_superadmin() and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")
    # contexte company pour filtrer les selects
    current_company = None if request.user.is_superadmin() else request.user.company
    if request.method == "POST":
        form = ReferralForm(request.POST, instance=obj, request=request, company=current_company)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = r.referrer.company
            r.save()
            return redirect("dashboard:referrals_list")
    else:
        form = ReferralForm(instance=obj, request=request, company=current_company)
    return render(request, "dashboard/referral_form.html", {"form": form})

@login_required
def referral_delete(request, pk):
    _require_company_staff(request.user)
    obj = get_object_or_404(Referral, pk=pk)
    if not request.user.is_superadmin() and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")
    if request.method == "POST":
        obj.delete()
        return redirect("dashboard:referrals_list")
    return render(request, "dashboard/confirm_delete.html", {
        "title": "Supprimer le parrainage",
        "message": "Confirmer la suppression de ce parrainage ?",
        "back_url": "dashboard:referrals_list",
    })
