# rewards/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import Company
from dashboard.models import Reward
from .forms import RewardForm

# -----------------------------
# Helpers placés AVANT les vues
# -----------------------------
def _company_for(request):
    """
    Admin entreprise -> sa company
    Superadmin       -> ?company=<slug|id> sinon None
    """
    c = getattr(getattr(request.user, "company", None), "id", None)
    if c:
        return request.user.company
    company_param = (request.GET.get("company") or "").strip()
    if company_param:
        return (
            Company.objects.filter(slug=company_param).first()
            or Company.objects.filter(pk=company_param).first()
        )
    return None

def _qs_rewards_for(user, company=None):
    if hasattr(user, "is_superadmin") and user.is_superadmin():
        qs = Reward.objects.select_related("company").order_by("-created_at")
        return qs.filter(company=company) if company else qs
    if hasattr(user, "is_admin_entreprise") and user.is_admin_entreprise():
        return (
            Reward.objects.select_related("company")
            .filter(company=user.company)
            .order_by("-created_at")
        )
    return Reward.objects.none()

# ------------
# Vues
# ------------
@login_required
def reward_list(request):
    company = _company_for(request) or getattr(request.user, "company", None)

    qs = _qs_rewards_for(request.user, company=company)

    state = (request.GET.get("state") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if state:
        qs = qs.filter(state=state)
    if q:
        qs = qs.filter(
            Q(label__icontains=q) |
            Q(code__icontains=q)
        )

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    base_qs = _qs_rewards_for(request.user, company=company)
    kpis = {
        "PENDING": base_qs.filter(state="PENDING").count(),
        "SENT": base_qs.filter(state="SENT").count(),
        "DISABLED": base_qs.filter(state="DISABLED").count(),
        "ARCHIVED": base_qs.filter(state="ARCHIVED").count(),
    }
    kpi_labels = [
        ("PENDING", "Cadeaux en attente"),
        ("SENT", "Cadeaux envoyés"),
        ("DISABLED", "Désactivés"),
        ("ARCHIVED", "Archivés"),
    ]

    return render(request, "rewards/list.html", {
        "page": page,
        "state": state,
        "q": q,
        "kpis": kpis,
        "kpi_labels": kpi_labels,
        "state_choices": getattr(Reward, "STATE_CHOICES", ()),
    })

@login_required
def reward_create(request):
    company = _company_for(request) or getattr(request.user, "company", None)
    if not company:
        messages.error(request, "Sélectionnez d’abord une entreprise.")
        return redirect("dashboard:superadmin")

    if request.method == "POST":
        form = RewardForm(request.POST)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = company
            r.client = None  # jamais d’attribution ici
            r.save()
            messages.success(request, "Récompense créée.")
            return redirect("rewards:list")
    else:
        form = RewardForm()
    return render(request, "rewards/form.html", {"form": form, "mode": "create"})

@login_required
def reward_update(request, pk):
    company = _company_for(request) or getattr(request.user, "company", None)
    qs = _qs_rewards_for(request.user, company=company)
    r = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        form = RewardForm(request.POST, instance=r)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = company
            r.client = None
            r.save()
            messages.success(request, "Récompense mise à jour.")
            return redirect("rewards:list")
    else:
        form = RewardForm(instance=r)
    return render(request, "rewards/form.html", {"form": form, "mode": "update"})

@login_required
def reward_delete(request, pk):
    company = _company_for(request) or getattr(request.user, "company", None)
    qs = _qs_rewards_for(request.user, company=company)
    r = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        r.delete()
        messages.success(request, "Récompense supprimée.")
        return redirect("rewards:list")

    return render(request, "rewards/confirm_delete.html", {"reward": r})
