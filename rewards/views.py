from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from dashboard.models import Reward, Client
from .forms import RewardForm
# rewards/views.py (extraits)
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from dashboard.models import Reward, Client
from .forms import RewardForm

STATE_CHOICES = getattr(
    Reward, "STATE_CHOICES",
    (("PENDING", "À envoyer"), ("SENT", "Envoyé"), ("DISABLED", "Désactivé"), ("ARCHIVED", "Archivé"))
)

def _qs_rewards_for(user):
    if hasattr(user, "is_superadmin") and user.is_superadmin():
        return Reward.objects.select_related("client", "company").order_by("-created_at")
    if hasattr(user, "is_admin_entreprise") and user.is_admin_entreprise():
        return Reward.objects.select_related("client", "company").filter(company=user.company).order_by("-created_at")
    return Reward.objects.none()

@login_required
def reward_list(request):
    qs = _qs_rewards_for(request.user)

    state = (request.GET.get("state") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if state:
        qs = qs.filter(state=state)
    if q:
        qs = qs.filter(
            Q(label__icontains=q) |
            Q(code__icontains=q)  |
            Q(client__first_name__icontains=q) |
            Q(client__last_name__icontains=q)  |
            Q(client__email__icontains=q)
        )

    page = Paginator(qs, 20).get_page(request.GET.get("page"))

    # KPIs
    base_qs = _qs_rewards_for(request.user)
    kpis = {
        "PENDING": base_qs.filter(state="PENDING").count(),
        "SENT": base_qs.filter(state="SENT").count(),
        "DISABLED": base_qs.filter(state="DISABLED").count(),
        "ARCHIVED": base_qs.filter(state="ARCHIVED").count(),
    }

    # Libellés jolis pour les cartes KPI
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
        "state_choices": STATE_CHOICES,  
        "kpi_labels": kpi_labels,        
    })


@login_required
def reward_create(request):
    if request.method == "POST":
        form = RewardForm(request.POST, request=request)
        if form.is_valid():
            r = form.save(commit=False)
            # Cohérence company
            r.company = r.client.company
            r.save()
            messages.success(request, "Récompense créée.")
            return redirect("rewards:list")
    else:
        form = RewardForm(request=request)
    return render(request, "rewards/form.html", {"form": form, "mode": "create"})

@login_required
def reward_update(request, pk):
    qs = _qs_rewards_for(request.user)
    r = get_object_or_404(qs, pk=pk)

    if request.method == "POST":
        form = RewardForm(request.POST, instance=r, request=request)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = r.client.company
            r.save()
            messages.success(request, "Récompense mise à jour.")
            return redirect("rewards:list")
    else:
        form = RewardForm(instance=r, request=request)
    return render(request, "rewards/form.html", {"form": form, "mode": "update"})

@login_required
def reward_delete(request, pk):
    qs = _qs_rewards_for(request.user)
    r = get_object_or_404(qs, pk=pk)
    if request.method == "POST":
        r.delete()
        messages.success(request, "Récompense supprimée.")
        return redirect("rewards:list")
    return render(request, "rewards/confirm_delete.html", {"reward": r})

@login_required
def reward_send_email(request, pk):
    # Bouchon : à brancher avec ton envoi réel
    qs = _qs_rewards_for(request.user)
    r = get_object_or_404(qs, pk=pk)
    # … envoi réel ici …
    messages.success(request, f"Mail envoyé pour « {r.label} » à {r.client.email or '—'}.")
    return redirect("rewards:list")
