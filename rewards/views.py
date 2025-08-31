# rewards/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST

from accounts.models import Company
from dashboard.models import Referral
from .models import RewardTemplate, Reward
from django.utils import timezone 


BUCKET_UI = {
    "SOUVENT":   {"label": "Souvent",   "badge": "success", "prob": "980/1000"},
    "MOYEN":     {"label": "Moyen",     "badge": "info",    "prob": "19/1000"},
    "RARE":      {"label": "Rare",      "badge": "warning", "prob": "1/1000"},
    "TRES_RARE": {"label": "Très rare", "badge": "danger",  "prob": "1/100000"},
}

STATE_UI = {
    "PENDING":  {"label": "En attente",   "badge": "warning"},
    "SENT":     {"label": "Envoyée",      "badge": "success"},
    "DISABLED": {"label": "Désactivée",   "badge": "secondary"},
    "ARCHIVED": {"label": "Archivée",     "badge": "dark"},
}


def _current_company(request):
    """
    super simple : admin entreprise = user.company ; superadmin -> ?company=<id>
    """
    user = request.user
    company = getattr(user, "company", None)
    cid = (request.GET.get("company") or "").strip()
    if getattr(user, "is_superadmin", lambda: False)() and cid:
        company = get_object_or_404(Company, pk=cid)
    return company


def _can_manage_company(user, company) -> bool:
    return (hasattr(user, "is_superadmin") and user.is_superadmin()) or (
        hasattr(user, "company") and user.company_id == company.id
    )


def ensure_reward_templates(company):
    """
    Crée les 4 lignes si manquantes, avec probabilités affichées figées.
    """
    for key, ui in BUCKET_UI.items():
        obj, created = RewardTemplate.objects.get_or_create(
            company=company, bucket=key,
            defaults={
                "label": "- 10 % de remise" if key in ("SOUVENT", "MOYEN") else (
                    "iPhone 16 Pro Max" if key == "RARE" else "Voyage à Miami"
                ),
                "cooldown_months": 1 if key in ("SOUVENT", "MOYEN") else (3 if key == "RARE" else 6),
                "probability_display": ui["prob"],
                "min_referrals_required": 0,
            }
        )
        if not obj.probability_display:
            obj.probability_display = ui["prob"]
            obj.save(update_fields=["probability_display"])


# ----------------------------- VUES CRUD TEMPLATES -----------------------------

@login_required
def reward_list(request):
    company = _current_company(request)
    if not company:
        messages.error(request, "Aucune entreprise sélectionnée.")
        return redirect("dashboard:root")

    ensure_reward_templates(company)
    items = RewardTemplate.objects.filter(company=company)

    # ordre voulu : Souvent → Moyen → Rare → Très rare
    order = {"SOUVENT": 0, "MOYEN": 1, "RARE": 2, "TRES_RARE": 3}
    items = sorted(items, key=lambda r: order.get(r.bucket, 99))

    # pour l’affichage couleur/badge
    items = [(r, BUCKET_UI[r.bucket]) for r in items]
    return render(request, "rewards/list.html", {"items": items})


from .forms import RewardTemplateForm  # si tu as un formulaire d’édition

@login_required
def reward_update(request, pk):
    company = _current_company(request)
    r = get_object_or_404(RewardTemplate, pk=pk, company=company)
    if request.method == "POST":
        form = RewardTemplateForm(request.POST, instance=r)
        if form.is_valid():
            form.save()
            messages.success(request, "Récompense mise à jour.")
            return redirect("rewards:list")
    else:
        form = RewardTemplateForm(instance=r)
    return render(request, "rewards/form.html", {"form": form, "tpl": r, "ui": BUCKET_UI[r.bucket]})


# ------------------------------ HISTORIQUE (ENTREPRISE) ------------------------------

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render, redirect

# suppose que _current_company, BUCKET_UI, STATE_UI, Reward sont déjà importés/définis plus haut

@login_required
def rewards_history_company(request):
    """
    Historique de TOUTES les récompenses d'une entreprise (tous les clients).
    Filtres: bucket, état, recherche. Pagination.
    """
    company = _current_company(request)
    if not company:
        messages.error(request, "Aucune entreprise sélectionnée.")
        return redirect("dashboard:root")

    # ✅ Précharge client, referral, parrain et filleul pour éviter les N+1
    qs = (
        Reward.objects
        .select_related(
            "client",
            "referral",
            "referral__referrer",
            "referral__referee",
        )
        .filter(company=company)
        .order_by("-created_at", "-id")
    )

    bucket = (request.GET.get("bucket") or "").strip().upper()
    state  = (request.GET.get("state") or "").strip().upper()
    q      = (request.GET.get("q") or "").strip()

    if bucket in BUCKET_UI.keys():
        qs = qs.filter(bucket=bucket)
    if state in STATE_UI.keys():
        qs = qs.filter(state=state)
    if q:
        qs = qs.filter(
            Q(client__first_name__icontains=q) |
            Q(client__last_name__icontains=q)  |
            Q(client__email__icontains=q)      |
            Q(label__icontains=q)
        )

    page = Paginator(qs, 20).get_page(request.GET.get("p"))

    return render(request, "rewards/history.html", {
        "company": company,
        "page": page,
        "bucket": bucket,
        "state": state,
        "q": q,
        "BUCKET_UI": BUCKET_UI,
        "STATE_UI": STATE_UI,
        "buckets": [(k, v["label"]) for k, v in BUCKET_UI.items()],
        "states": [(k, v["label"]) for k, v in STATE_UI.items()],
    })

# ------------------------------ ROUE / SPIN ------------------------------

@login_required
def reward_spin(request, reward_id: int):
    """
    Page avec une roue animée et des couleurs qui correspondent au type de récompense.
    - Segments fixes (SOUVENT/MOYEN/RARE/TRES_RARE).
    """
    reward = get_object_or_404(
        Reward.objects.select_related("company", "client"),
        pk=reward_id
    )

    wheel_order = ["SOUVENT", "MOYEN", "RARE", "TRES_RARE"]
    segment = 360 / len(wheel_order)  # 90°
    try:
        idx = wheel_order.index(reward.bucket)
    except ValueError:
        idx = 0
    target_angle = 4 * 360 + int(idx * segment + segment / 2)

    ui = BUCKET_UI.get(reward.bucket, {"label": reward.bucket, "badge": "secondary"})
    return render(request, "rewards/spin.html", {
        "reward": reward,
        "ui": ui,
        "target_angle": target_angle,
    })


# ------------------------------ PAGE PUBLIQUE (token) ------------------------------

def use_reward(request, token):
    """
    Page publique : N’ALTÈRE PAS L’ÉTAT.
    Affiche la récompense et explique que l’équipe validera en caisse.
    """
    reward = get_object_or_404(Reward, token=token)

    context = {"reward": reward}
    if reward.state != "PENDING":
        messages.info(request, "Cette récompense n’est plus en attente (déjà distribuée ou inactive).")
    return render(request, "rewards/use_reward.html", context)


# ------------------------------ ACTIONS ------------------------------

@login_required
@require_POST
def distribute_reward(request, pk: int):
    """
    Action opérateur/admin : passe la récompense en SENT.
    """
    reward = get_object_or_404(
        Reward.objects.select_related("company", "client"),
        pk=pk
    )

    if not _can_manage_company(request.user, reward.company):
        messages.error(request, "Accès refusé.")
        back_id = request.POST.get("back_client")
        return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("dashboard:clients_list")

    if reward.state != "PENDING":
        messages.info(request, "La récompense n’est pas en attente (déjà traitée ?).")
    else:
        reward.state = "SENT"
        reward.redeemed_at = timezone.now()
        reward.save(update_fields=["state", "redeemed_at"])
        messages.success(request, f"Récompense « {reward.label} » distribuée.")

    back_id = request.POST.get("back_client")
    return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("rewards:history_company")


@login_required
@require_POST
def referral_delete(request, pk: int):
    """
    Suppression d’un parrainage (avec contrôle périmètre).
    """
    referral = get_object_or_404(
        Referral.objects.select_related("company", "referrer", "referee"),
        pk=pk
    )

    if not _can_manage_company(request.user, referral.company):
        messages.error(request, "Accès refusé.")
        back_id = request.POST.get("back_client")
        return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("dashboard:clients_list")

    back_client_id = request.POST.get("back_client") or referral.referee_id or referral.referrer_id

    referral.delete()
    messages.success(request, "Parrainage supprimé.")
    return redirect("dashboard:client_detail", pk=back_client_id)
