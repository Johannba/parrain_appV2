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
from rewards.models import Reward, RewardTemplate
from rewards.forms import RewardTemplateForm

# Tirage de récompense
from rewards.services.probabilities import tirer_recompense, SOUVENT, MOYEN, RARE, TRES_RARE
from django.db import transaction

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




# On suppose que ces helpers existent déjà dans ce module
# def _require_company_staff(user): ...
# def _is_superadmin(user): ...
login_required
def client_detail(request, pk: int):
    _require_company_staff(request.user)

    u = request.user
    if _is_superadmin(u):
        client = get_object_or_404(
            Client.objects.select_related("company"),
            pk=pk
        )
    else:
        client = get_object_or_404(
            Client.objects.select_related("company"),
            pk=pk,
            company=u.company
        )

    # ---------- Historique des parrainages impliquant ce client ----------
    history_qs = (
        Referral.objects
        .select_related("referrer", "referee")
        .filter(company=client.company)
        .filter(Q(referrer=client) | Q(referee=client))
        .order_by("-created_at", "-id")
    )
    history_page = Paginator(history_qs, 8).get_page(request.GET.get("h"))

    # Map referral_id -> reward_id (reward déjà attribuée au PARRAIN pour ce parrainage)
    ref_ids = [r.id for r in history_page.object_list]
    rewards_for_rows = (
        Reward.objects
        .filter(company=client.company, client=client, referral_id__in=ref_ids)
        .exclude(state="DISABLED")
        .values_list("referral_id", "id")
    )
    ref_rewards = {ref_id: reward_id for ref_id, reward_id in rewards_for_rows}

    # Annote chaque ligne de l’historique (utilisé par le template)
    for r in history_page.object_list:
        r.existing_reward_id = ref_rewards.get(r.id)

    # ---------- Récompenses par statut (3 colonnes) ----------
    rewards_ok = (
        Reward.objects
        .filter(company=client.company, client=client, state="SENT")
        .order_by("-id")
    )
    rewards_pending = (
        Reward.objects
        .filter(company=client.company, client=client, state="PENDING")
        .order_by("-id")
    )
    rewards_unused = (
        Reward.objects
        .filter(company=client.company, client=client, state="DISABLED")
        .order_by("-id")
    )

    # KPIs
    kpi_obtenus  = rewards_ok.count()
    kpi_attente  = rewards_pending.count()
    kpi_nonutils = rewards_unused.count()

    # Pagination des 3 blocs
    page_ok      = Paginator(rewards_ok, 5).get_page(request.GET.get("ok"))
    page_pending = Paginator(rewards_pending, 5).get_page(request.GET.get("pending"))
    page_unused  = Paginator(rewards_unused, 5).get_page(request.GET.get("unused"))

    # ❌ NE PAS écrire rw.claim_url (propriété sans setter) — on utilisera claim_path au template.
    # (Si tu tiens à pré-calculer l’URL absolue côté vue, fais-le dans une structure à part)
    # Exemple si besoin :
    # base = f"{request.scheme}://{request.get_host()}"
    # for rw in page_pending.object_list:
    #     rw._claim_abs = f"{base}{reverse('rewards:use_reward', kwargs={'token': rw.token})}" if rw.token else ""

    return render(request, "dashboard/client_detail.html", {
        "company": client.company,
        "client": client,
        "history_page": history_page,
        "page_ok": page_ok,
        "page_pending": page_pending,
        "page_unused": page_unused,
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
def referral_delete(request, pk: int):
    """
    Supprime un parrainage.
    - Si un champ POST 'back_client' est présent => on revient sur la fiche client.
    - Sinon => on revient sur la liste des clients.
    """
    _require_company_staff(request.user)

    obj = get_object_or_404(Referral, pk=pk)

    # Sécurité : un admin d’entreprise ne peut agir que sur sa company
    if not _is_superadmin(request.user) and obj.company_id != getattr(request.user, "company_id", None):
        raise PermissionDenied("Accès refusé.")

    # Détermine où revenir
    back_client_id = request.POST.get("back_client") or request.GET.get("back_client")
    back_url_name = "dashboard:client_detail" if back_client_id else "dashboard:clients_list"
    back_url_kwargs = {"pk": back_client_id} if back_client_id else {}

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Parrainage supprimé.")
        return redirect(back_url_name, **back_url_kwargs)

    # GET : page de confirmation
    return render(request, "dashboard/confirm_delete.html", {
        "title": "Supprimer le parrainage",
        "message": "Confirmer la suppression de ce parrainage ?",
        "post_action": "dashboard:referral_delete",
        "post_kwargs": {"pk": obj.pk},
        "back_url_name": back_url_name,
        "back_url_kwargs": back_url_kwargs,
        "back_client_id": back_client_id,  # pour renvoyer l’info dans le POST
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
    Valide un parrainage et attribue la récompense au FILLEUL (referee),
    puis redirige vers l'animation.
    """
    _require_company_staff(request.user)

    referral = get_object_or_404(
        Referral.objects.select_related("referee", "referrer", "company"),
        pk=referral_id
    )

    user_company = _company_for(request.user)
    if user_company and referral.company_id != user_company.id and not _is_superadmin(request.user):
        messages.error(request, "Ce parrainage n’appartient pas à votre entreprise.")
        return redirect("dashboard:clients_list")

    # Bénéficiaire = FILLEUL
    client = referral.referee

    # Tirage exact
    token = tirer_recompense(referral.company)

    # Clone du template correspondant au token tiré
    tpl = get_object_or_404(RewardTemplate, company=referral.company, bucket=token)

    reward = Reward.objects.create(
        company=referral.company,
        client=client,
        referral=referral,          # ← on trace le lien (clé de la règle métier)
        label=tpl.label,
        bucket=token,
        cooldown_days=tpl.cooldown_days,
        state="PENDING",
    )

    messages.success(
        request,
        f"Parrainage validé. Récompense pour le filleul « {client} » : {tpl.label}."
    )
    return redirect("rewards:spin", reward_id=reward.id)


# ---------------------------
# ATTRIBUER AU PARRAIN (referrer)
# ---------------------------
@login_required
@transaction.atomic
def validate_referral_and_award_referrer(request, referral_id: int):
    """
    Attribue une récompense au PARRAIN (referrer) pour CE parrainage.
    - Autorise plusieurs rewards au même parrain SI ce sont des filleuls différents.
    - Interdit 2 rewards pour le même (parrain, filleul) => vérifié via referral.
    """
    referral = get_object_or_404(
        Referral.objects.select_related("referee", "referrer", "company"),
        pk=referral_id
    )
    company = referral.company
    referrer = referral.referrer  # bénéficiaire de la reward

    # 1) Anti-doublon : existe déjà une reward pour CE (parrain, referral) ?
    existing = Reward.objects.filter(company=company, client=referrer, referral=referral)\
                             .exclude(state="DISABLED")\
                             .order_by("-id")\
                             .first()
    if existing:
        messages.info(request, "Une récompense existe déjà pour ce parrain et ce filleul.")
        return redirect("rewards:spin", reward_id=existing.id)

    # 2) Tirage EXACT (roues) puis clonage du template correspondant
    token = tirer_recompense(company)
    tpl = get_object_or_404(RewardTemplate, company=company, bucket=token)

    reward = Reward.objects.create(
        company=company,
        client=referrer,
        referral=referral,          # ← on trace le lien (clé de la règle métier)
        label=tpl.label,
        bucket=token,
        cooldown_days=tpl.cooldown_days,
        state="PENDING",
    )

    messages.success(request, f"Récompense attribuée au parrain « {referrer} » pour le filleul « {referral.referee} » : {tpl.label}.")
    return redirect("rewards:spin", reward_id=reward.id)