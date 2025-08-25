# rewards/views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from accounts.models import Company
from .models import RewardTemplate
from .forms import RewardTemplateForm
from dashboard.models import Referral
from django.views.decorators.http import require_POST

BUCKET_UI = {
    "SOUVENT":   {"label": "Souvent",   "badge": "success", "prob": "80/100"},
    "MOYEN":     {"label": "Moyen",     "badge": "info",    "prob": "19/100"},
    "RARE":      {"label": "Rare",      "badge": "warning", "prob": "1/100"},
    "TRES_RARE": {"label": "Très rare", "badge": "danger",  "prob": "1/10000"},
}

def _current_company(request):
    # super simple : admin entreprise = user.company ; superadmin -> ?company=<id>
    user = request.user
    company = getattr(user, "company", None)
    cid = (request.GET.get("company") or "").strip()
    if getattr(user, "is_superadmin", lambda: False)() and cid:
        company = get_object_or_404(Company, pk=cid)
    return company

def ensure_reward_templates(company):
    """Crée les 4 lignes si manquantes, avec proba figées."""
    for key, ui in BUCKET_UI.items():
        obj, created = RewardTemplate.objects.get_or_create(
            company=company, bucket=key,
            defaults={
                "label": "- 10 % de remise" if key in ("SOUVENT", "MOYEN") else (
                    "iPhone 16 Pro Max" if key=="RARE" else "Voyage à Miami"
                ),
                "cooldown_months": 1 if key in ("SOUVENT", "MOYEN") else (3 if key=="RARE" else 6),
                "probability_display": ui["prob"],
            }
        )
        # si la ligne existe mais le texte affiché est vide (ancienne data), on le remet
        if not obj.probability_display:
            obj.probability_display = ui["prob"]
            obj.save(update_fields=["probability_display"])

@login_required
def reward_list(request):
    company = _current_company(request)
    if not company:
        messages.error(request, "Aucune entreprise sélectionnée.")
        return redirect("dashboard:root")

    ensure_reward_templates(company)
    items = RewardTemplate.objects.filter(company=company)

    # pour l’affichage couleur/badge
    items = [
        (r, BUCKET_UI[r.bucket])
        for r in items
    ]
    return render(request, "rewards/list.html", {"items": items})

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


def _can_manage_company(user, company) -> bool:
    return (hasattr(user, "is_superadmin") and user.is_superadmin()) or (
        hasattr(user, "company") and user.company_id == company.id
    )

@login_required
@require_POST
def referral_delete(request, pk: int):
    referral = get_object_or_404(Referral.objects.select_related("company", "referrer", "referee"), pk=pk)

    # sécurité : périmètre entreprise
    if not _can_manage_company(request.user, referral.company):
        messages.error(request, "Accès refusé.")
        # on tente de revenir sur la fiche passée en paramètre, sinon liste
        back_id = request.POST.get("back_client")
        return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("dashboard:clients_list")

    # pour le redirect, on récupère la fiche d’où on a cliqué
    back_client_id = request.POST.get("back_client") or referral.referee_id or referral.referrer_id

    referral.delete()
    messages.success(request, "Parrainage supprimé.")
    return redirect("dashboard:client_detail", pk=back_client_id)