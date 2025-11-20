# rewards/views.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
import random

logger = logging.getLogger(__name__)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.db.models.functions import TruncMonth
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Company
from dashboard.models import Referral
from rewards.services import award_both_parties
from .models import RewardTemplate, Reward, ProbabilityWheel
from .forms import RewardTemplateForm
from rewards.services.probabilities import BASE_COUNTS, VR_COUNTS, BASE_SIZE, VR_SIZE
from .services.smsmode import SMSPayload, send_sms, build_reward_sms_text
from common.phone_utils import normalize_msisdn

# ----------------------------- UI Dictionaries -----------------------------

BUCKET_UI = {
    "SOUVENT":   {"label": "Souvent",   "badge": "success", "prob": "980/1000"},
    "MOYEN":     {"label": "Moyen",     "badge": "info",    "prob": "19/1000"},
    "RARE":      {"label": "Rare",      "badge": "warning", "prob": "1/1000"},
    "TRES_RARE": {"label": "Très rare", "badge": "danger",  "prob": "1/100000"},
}

STATE_UI = {
    "PENDING":  {"label": "En attente",   "badge": "warning"},
    "SENT":     {"label": "Envoyée",      "badge": "success"},
}


# ----------------------------- Helpers généraux -----------------------------

def _is_superadmin(u) -> bool:
    return hasattr(u, "is_superadmin") and u.is_superadmin()

def _company_for(u):
    return getattr(u, "company", None)

def _current_company(request, *, allow_default_for_superadmin: bool = True) -> Company | None:
    """
    Admin/Opérateur : user.company
    Superadmin :
      - si ?company=… fourni → utilise cet id (string possible)
      - sinon id mémorisé en session (souvent un int)
      - sinon (si allow_default_for_superadmin) → 1ʳᵉ entreprise
    """
    user = request.user

    # Cas Admin/Opérateur : on retourne simplement son entreprise
    if not _is_superadmin(user):
        return getattr(user, "company", None)

    # ---- Superadmin : on lit d'abord le GET (string) puis la session (int) ----
    raw_cid = request.GET.get("company")
    if isinstance(raw_cid, str):
        raw_cid = raw_cid.strip()
    if not raw_cid:
        raw_cid = request.session.get("dash_company_id")  # peut être un int

    # On résout l'entreprise (Django accepte int/str pour pk)
    company = Company.objects.filter(pk=raw_cid).first() if raw_cid else None
    if company:
        request.session["dash_company_id"] = company.id  # on stocke proprement l'int
        return company

    # Fallback : 1ʳᵉ entreprise (si autorisé)
    if allow_default_for_superadmin:
        company = Company.objects.order_by("name").first()
        if company:
            request.session["dash_company_id"] = company.id
        return company

    return None


def _can_manage_company(user, company) -> bool:
    return _is_superadmin(user) or (getattr(user, "company_id", None) == company.id)


def ensure_reward_templates(company: Company):
    """
    Crée les 4 templates si manquants, avec probas affichées figées.
    (Utilisé pour un écran mono-entreprise : liste/édition des templates)
    """
    defaults_map = {
        "SOUVENT":   {"label": "- 10 % de remise", "cooldown_months": 1},
        "MOYEN":     {"label": "- 10 % de remise", "cooldown_months": 1},
        "RARE":      {"label": "iPhone 16 Pro Max", "cooldown_months": 3},
        "TRES_RARE": {"label": "Voyage à Miami", "cooldown_months": 6},
    }
    for key, ui in BUCKET_UI.items():
        obj, _created = RewardTemplate.objects.get_or_create(
            company=company, bucket=key,
            defaults={
                **defaults_map[key],
                "probability_display": ui["prob"],
                "min_referrals_required": 0,
            }
        )
        if not obj.probability_display:
            obj.probability_display = ui["prob"]
            obj.save(update_fields=["probability_display"])


def _last_12_month_starts(today):
    """
    Retourne la liste des 12 premiers jours de mois (du plus ancien au plus récent).
    """
    y, m = today.year, today.month
    out = []
    for i in range(11, -1, -1):
        yy, mm = y, m - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(date(yy, mm, 1))
    return out


# ----------------------------- Snapshot des roues (local) -----------------------------
# Clés/tokens alignés avec rewards/probabilities.py
_BASE_KEY = "base_100"
_VERY_RARE_KEY = "very_rare_10000"

_TOK_BASE = ["SOUVENT", "MOYEN", "RARE"]
_TOK_VR   = ["TRES_RARE", "NO_HIT"]


def _remaining_counts(pool, idx, tokens):
    """Compte ce qu'il reste AVANT la fin du cycle actuel (de idx -> fin)."""
    tail = pool[idx:] if pool and 0 <= idx < len(pool) else pool
    out = {}
    for t in tokens:
        out[t] = tail.count(t) if tail else 0
    return out


def _wheels_snapshot(company: Company):
    """
    Renvoie un dict:
    {
      "base":      {"size": int, "idx": int, "progress_pct": int,
                    "remaining_by_token": {token: n}, "total_by_token": {token: n}},
      "very_rare": { ... }
    }
    Si une roue n'existe pas encore, on renvoie des zéros élégants.
    """
    snap = {}
    # --- BASE ---
    try:
        base = ProbabilityWheel.objects.get(company=company, key=_BASE_KEY)
        base_total = {t: base.pool.count(t) for t in _TOK_BASE}
        base_remaining = _remaining_counts(base.pool, base.idx, _TOK_BASE)
        base_progress = int((base.idx / base.size) * 100) if base.size else 0
        snap["base"] = {
            "size": base.size,
            "idx": base.idx,
            "progress_pct": base_progress,
            "remaining_by_token": base_remaining,
            "total_by_token": base_total,
        }
    except ProbabilityWheel.DoesNotExist:
        snap["base"] = {
            "size": 0,
            "idx": 0,
            "progress_pct": 0,
            "remaining_by_token": {t: 0 for t in _TOK_BASE},
            "total_by_token": {t: 0 for t in _TOK_BASE},
        }

    # --- VERY RARE ---
    try:
        vr = ProbabilityWheel.objects.get(company=company, key=_VERY_RARE_KEY)
        vr_total = {t: vr.pool.count(t) for t in _TOK_VR}
        vr_remaining = _remaining_counts(vr.pool, vr.idx, _TOK_VR)
        vr_progress = int((vr.idx / vr.size) * 100) if vr.size else 0
        snap["very_rare"] = {
            "size": vr.size,
            "idx": vr.idx,
            "progress_pct": vr_progress,
            "remaining_by_token": vr_remaining,
            "total_by_token": vr_total,
        }
    except ProbabilityWheel.DoesNotExist:
        snap["very_rare"] = {
            "size": 0,
            "idx": 0,
            "progress_pct": 0,
            "remaining_by_token": {t: 0 for t in _TOK_VR},
            "total_by_token": {t: 0 for t in _TOK_VR},
        }

    return snap


# ----------------------------- CRUD Templates -----------------------------

@login_required
def reward_list(request):
    """
    Écran de gestion des templates de récompenses.
    - Admin/Opérateur : sur son entreprise.
    - Superadmin : PAS de choix requis → on prend automatiquement la 1ʳᵉ entreprise
      (ou celle passée en ?company=... si présent).
    """
    company = _current_company(request, allow_default_for_superadmin=True)
    if not company:
        # Cas extrême : aucune entreprise en base
        messages.info(request, "Aucune entreprise disponible.")
        return render(request, "rewards/list.html", {"items": [], "TEST_WHEEL": None, "company": None})

    # S’assure que les 4 templates existent pour cette entreprise (mono-contexte)
    ensure_reward_templates(company)

    # 1) Récupérer les templates
    qs = RewardTemplate.objects.filter(company=company)

    # 2) Trier par bucket (SOUVENT -> MOYEN -> RARE -> TRES_RARE)
    order = {"SOUVENT": 0, "MOYEN": 1, "RARE": 2, "TRES_RARE": 3}
    items_sorted = sorted(qs, key=lambda tpl: order.get(tpl.bucket, 99))

    # 3) Préparer l'affichage (paire (template, ui))
    items = [(tpl, BUCKET_UI[tpl.bucket]) for tpl in items_sorted]

    # 4) Données de la roue de test (probas identiques à Reward)
    test_wheel = {
        "base": {"size": BASE_SIZE, "counts": BASE_COUNTS},
        "very_rare": {"size": VR_SIZE, "counts": VR_COUNTS},
    }

    return render(request, "rewards/list.html", {
        "company": company,
        "items": items,
        "TEST_WHEEL": test_wheel,
        "is_superadmin": _is_superadmin(request.user),
    })


@login_required
def reward_update(request, pk):
    company = _current_company(request, allow_default_for_superadmin=True)
    r = get_object_or_404(RewardTemplate, pk=pk, company=company)
    if request.method == "POST":
        form = RewardTemplateForm(request.POST, instance=r)
        if form.is_valid():
            form.save()
            messages.success(request, "Récompense mise à jour.")
            return redirect("rewards:list")
    else:
        form = RewardTemplateForm(instance=r)
    return render(request, "rewards/form.html", {"form": form, "tpl": r, "ui": BUCKET_UI[r.bucket], "company": company})


# ------------------------------ Historique (entreprise / global) ------------------------------

@login_required
def rewards_history_company(request):
    """
    Historique des récompenses.
    - Superadmin SANS ?company=… : historique GLOBAL (toutes entreprises).
    - Sinon : historique filtré par entreprise.
    """
    user = request.user

    base_qs = (
        Reward.objects
        .select_related("company", "client", "referral", "referral__referrer", "referral__referee")
        .order_by("-created_at", "-id")
    )

    # ---- Global si Superadmin sans paramètre ----
    if _is_superadmin(user) and not request.GET.get("company"):
        qs = base_qs
        company = None
        scope_label = "GLOBAL"
    else:
        company = _current_company(request)  # comportement existant conservé
        if not company:
            messages.error(request, "Aucune entreprise sélectionnée.")
            return redirect("dashboard:root")
        qs = base_qs.filter(company=company)
        scope_label = company.name

    # Filtres UI
    bucket = (request.GET.get("bucket") or "").strip().upper()
    state  = (request.GET.get("state") or "").strip().upper()
    q      = (request.GET.get("q") or "").strip()

    if bucket in BUCKET_UI:
        qs = qs.filter(bucket=bucket)
    if state in STATE_UI:
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
        "company": company,                # None en mode global
        "scope_label": scope_label,        # "GLOBAL" ou nom d’entreprise
        "page": page,
        "bucket": bucket,
        "state": state,
        "q": q,
        "BUCKET_UI": BUCKET_UI,
        "STATE_UI": STATE_UI,
        "buckets": [(k, v["label"]) for k, v in BUCKET_UI.items()],
        "states": [(k, v["label"]) for k, v in STATE_UI.items()],
        "is_superadmin": _is_superadmin(user),
    })

# ------------------------------ Spin (animation) ------------------------------

@login_required
def reward_spin(request, reward_id: int):
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


# ------------------------------ Page publique (token) ------------------------------

def use_reward(request, token):
    """
    Page publique d'une récompense (par token) avec un rendu "joli".
    AUCUN changement de logique métier : on enrichit juste le contexte.
    """
    reward = get_object_or_404(
        Reward.objects.select_related(
            "company", "client", "referral", "referral__referrer", "referral__referee"
        ),
        token=token,
    )

    # Message informatif si la récompense n'est plus en attente
    if reward.state != "PENDING":
        messages.info(
            request,
            "Cette récompense n’est plus en attente (déjà distribuée ou inactive)."
        )

    # Données d'en-tête
    company_name = (getattr(reward.company, "name", "") or "").strip()
    client_name  = (reward.client.first_name or reward.client.last_name or "").strip()

    # Si la récompense provient d'un parrainage, on personnalise :
    is_ref = bool(reward.referral_id)
    is_referrer = is_ref and reward.client_id == reward.referral.referrer_id
    is_referee  = is_ref and reward.client_id == reward.referral.referee_id

    referrer_name = ""
    referee_name  = ""
    if is_ref:
        referrer_name = (reward.referral.referrer.first_name or reward.referral.referrer.last_name or "").strip()
        referee_name  = (reward.referral.referee.first_name  or reward.referral.referee.last_name  or "").strip()

    # Phrases d'accroche (comme sur la maquette)
    if is_referrer:
        headline  = f"Félicitations {client_name} !" if client_name else "Félicitations !"
        celebrate = f"Tu as fait découvrir {company_name} à {referee_name}".strip()
        subline   = "Voici ton cadeau 🎁"
        ribbon    = f"Parrainage validé grâce à {referee_name}".strip()
    elif is_referee:
        headline  = f"Bienvenue {client_name} !" if client_name else "Bienvenue !"
        celebrate = f"Parrainage validé grâce à {referrer_name}".strip()
        subline   = "Voici ton cadeau 🎁"
        ribbon    = "Ton cadeau"
    else:
        headline  = f"Félicitations {client_name} !" if client_name else "Félicitations !"
        celebrate = company_name
        subline   = "Voici ton cadeau 🎁"
        ribbon    = "Ton cadeau"

    claim_absolute = request.build_absolute_uri(reward.claim_path) if reward.claim_path else ""

    context = {
        "reward": reward,
        "headline": headline,
        "celebrate": celebrate,
        "subline": subline,
        "ribbon": ribbon,
        "company_name": company_name,
        "claim_absolute": claim_absolute,
    }
    return render(request, "rewards/use_reward.html", context)


# ------------------------------ Actions ------------------------------

@login_required
@require_POST
def distribute_reward(request, pk: int):
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


# ------------------------------ STATS (récompenses) ------------------------------

@login_required
def rewards_stats(request):
    """
    Superadmin sans ?company=... => stats GLOBAL (toutes entreprises)
    Sinon => stats bornées à l’entreprise courante.
    """
    user = request.user

    # ---- Superadmin GLOBAL (on n'utilise pas _current_company ici) ----
    if _is_superadmin(user) and not request.GET.get("company"):
        # Période (4 derniers mois)
        def _last_n_month_starts(today, n):
            y, m = today.year, today.month
            out = []
            for i in range(n - 1, -1, -1):
                yy, mm = y, m - i
                while mm <= 0:
                    mm += 12
                    yy -= 1
                out.append(date(yy, mm, 1))
            return out

        today = timezone.now().date().replace(day=1)
        months = _last_n_month_starts(today, 4)

        qs_all = Reward.objects.all()

        monthly_raw = (
            qs_all.annotate(m=TruncMonth("created_at"))
                  .values("m").annotate(n=Count("id")).order_by("m")
        )
        monthly_map = {row["m"].date(): row["n"] for row in monthly_raw if row["m"]}
        monthly_rows = [{"month": m, "n": monthly_map.get(m, 0)} for m in months]
        max_n = max([r["n"] for r in monthly_rows] or [1])
        for r in monthly_rows:
            r["pct"] = int((r["n"] / max_n) * 100) if max_n else 0

        gifts_raw = list(qs_all.values("label").annotate(n=Count("id")).order_by("-n")[:4])
        total_gifts = sum(g["n"] for g in gifts_raw) or 1
        top_gifts = [
            {"label": g["label"] or "—", "n": g["n"], "pct": int((g["n"] / total_gifts) * 100)}
            for g in gifts_raw
        ]

        # KPI + tableau par entreprise
        rows = []
        totals = {"rewards_sent": 0, "rewards_pending": 0, "clients": 0, "referrals_month": 0}
        month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for c in Company.objects.all().order_by("name"):
            r_sent = Reward.objects.filter(company=c, state="SENT").count()
            r_pend = Reward.objects.filter(company=c, state="PENDING").count()
            n_clients = c.client_set.count() if hasattr(c, "client_set") else 0
            n_ref_month = Referral.objects.filter(company=c, created_at__gte=month_start).count()
            rows.append({
                "company": c,
                "rewards_sent": r_sent,
                "rewards_pending": r_pend,
                "clients": n_clients,
                "referrals_month": n_ref_month,
            })
            totals["rewards_sent"] += r_sent
            totals["rewards_pending"] += r_pend
            totals["clients"] += n_clients
            totals["referrals_month"] += n_ref_month

        return render(request, "rewards/stats.html", {
            "company": None,              # important : pas d’entreprise sélectionnée
            "is_superadmin": True,
            "monthly_rows": monthly_rows,
            "top_gifts": top_gifts,
            "global_rows": rows,          # tableau par entreprise
            "global_kpi": totals,         # totaux globaux
        })

    # ---- Entreprise (Admin/Opérateur OU Superadmin avec ?company=...) ----
    company = _current_company(request)  # comportement existant conservé
    if not company:
        messages.error(request, "Aucune entreprise sélectionnée.")
        return redirect("dashboard:root")

    qs = Reward.objects.filter(company=company)

    # 4 derniers mois
    def _last_n_month_starts(today, n):
        y, m = today.year, today.month
        out = []
        for i in range(n - 1, -1, -1):
            yy, mm = y, m - i
            while mm <= 0:
                mm += 12
                yy -= 1
            out.append(date(yy, mm, 1))
        return out

    today = timezone.now().date().replace(day=1)
    months = _last_n_month_starts(today, 4)

    monthly_raw = (
        qs.annotate(m=TruncMonth("created_at"))
          .values("m").annotate(n=Count("id")).order_by("m")
    )
    monthly_map = {row["m"].date(): row["n"] for row in monthly_raw if row["m"]}
    monthly_rows = [{"month": m, "n": monthly_map.get(m, 0)} for m in months]
    max_n = max([r["n"] for r in monthly_rows] or [1])
    for r in monthly_rows:
        r["pct"] = int((r["n"] / max_n) * 100) if max_n else 0

    gifts_raw = list(qs.values("label").annotate(n=Count("id")).order_by("-n")[:4])
    total_gifts = sum(g["n"] for g in gifts_raw) or 1
    top_gifts = [
        {"label": g["label"] or "—", "n": g["n"], "pct": int((g["n"] / total_gifts) * 100)}
        for g in gifts_raw
    ]

    return render(request, "rewards/stats.html", {
        "company": company,
        "is_superadmin": _is_superadmin(user),
        "monthly_rows": monthly_rows,
        "top_gifts": top_gifts,
    })


# ------------------------------ Roue de test (sans attribution) ------------------------------

@login_required
def test_wheel(request):
    """
    Roue de test (sans attribution).

    Probabilités « de base » (sans minimums) :
      - SOUVENT   = 80 / 100
      - MOYEN     = 19 / 100
      - RARE      = 0,99999 / 100
      - TRES_RARE = 1 / 100000

    Modes :
      - combined (défaut) : test TRES_RARE (1/100000), sinon base 80/19/~1%
      - base              : uniquement SOUVENT/MOYEN/RARE
      - very_rare         : TRES_RARE vs NO_HIT
    GET:
      - n    : simuler N tirages
      - seed : graine RNG (reproductible)
      - mode : combined | base | very_rare
    """
    mode = (request.GET.get("mode") or "combined").lower()
    simulate_n = int(request.GET.get("n") or 0)
    seed = request.GET.get("seed")
    rng = random.Random(seed) if seed else random

    # Probabilités demandées
    P_S  = Decimal("80") / Decimal("100")        # 0.80
    P_M  = Decimal("19") / Decimal("100")        # 0.19
    P_R  = Decimal("0.99999") / Decimal("100")   # 0.0099999
    P_TR = Decimal(1) / Decimal(100000)          # 0.00001

    ORDER = ("SOUVENT", "MOYEN", "RARE", "TRES_RARE", "NO_HIT")

    # ---- Tirage 1 coup (pour l’animation) : pondération simple ----
    def weighted_choice(weights: dict[str, Decimal]) -> str:
        total = float(sum(weights.values())) or 1.0
        x = rng.random() * total
        acc = 0.0
        for k in ORDER:
            if k in weights:
                acc += float(weights[k])
                if x < acc:
                    return k
        return next(iter(weights))

    def draw_once() -> str:
        if mode == "very_rare":
            return weighted_choice({"TRES_RARE": P_TR, "NO_HIT": Decimal(1) - P_TR})
        if mode == "base":
            return weighted_choice({"SOUVENT": P_S, "MOYEN": P_M, "RARE": P_R})
        # combined
        if rng.random() < float(P_TR):
            return "TRES_RARE"
        return weighted_choice({"SOUVENT": P_S, "MOYEN": P_M, "RARE": P_R})

    bucket = draw_once()

    # ---- Simulation N tirages (sans remise pour respecter 80/19/1 sur 100) ----
    counts = pct = None
    if simulate_n > 0:
        counts = {"SOUVENT": 0, "MOYEN": 0, "RARE": 0, "TRES_RARE": 0, "NO_HIT": 0}

        if mode == "very_rare":
            # N essais indépendants de proba 1/100000
            for _ in range(simulate_n):
                if rng.random() < float(P_TR):
                    counts["TRES_RARE"] += 1
                else:
                    counts["NO_HIT"] += 1

        else:
            # Base « exacte » : cycles de 100 cases (80/19/1), échantillonnage sans remise.
            full_cycles, rem = divmod(simulate_n, 100)
            counts["SOUVENT"] += 80 * full_cycles
            counts["MOYEN"]   += 19 * full_cycles
            counts["RARE"]    += 1  * full_cycles

            if rem:
                base_pool = ["SOUVENT"] * 80 + ["MOYEN"] * 19 + ["RARE"] * 1
                rng.shuffle(base_pool)
                for t in base_pool[:rem]:
                    counts[t] += 1

            if mode == "combined":
                # Injecte les très rares (très improbable sur 100 tirages)
                # On convertit autant de tirages base en TRES_RARE pour rester à N total.
                vr_hits = sum(1 for _ in range(simulate_n) if rng.random() < float(P_TR))
                for _ in range(vr_hits):
                    base_list = (
                        ["SOUVENT"] * counts["SOUVENT"] +
                        ["MOYEN"]   * counts["MOYEN"]   +
                        ["RARE"]    * counts["RARE"]
                    )
                    if base_list:
                        t = rng.choice(base_list)
                        counts[t] -= 1
                    counts["TRES_RARE"] += 1

        total = sum(counts.values()) or 1
        pct = {k: round(counts[k] * 100 / total, 2) for k in counts}

    # ---- UI / animation ----
    ui = BUCKET_UI.get(bucket, {"label": "Aucun gain", "badge": "secondary"})
    wheel_order = ["SOUVENT", "MOYEN", "RARE", "TRES_RARE"]
    seg = 360 / len(wheel_order)
    idx = wheel_order.index(bucket) if bucket in wheel_order else 0
    target_angle = 4 * 360 + int(idx * seg + seg / 2)

    return render(request, "rewards/test_wheel.html", {
        "bucket": bucket,
        "ui": ui,
        "target_angle": target_angle,
        "mode": mode,
        "seed": seed or "",
        "simulate_n": simulate_n,
        "counts": counts,
        "pct": pct,
    })


# ------------------------------ Envoi SMS lien de récompense ------------------------------

@login_required
@require_POST
def reward_send_sms(request, pk: int):
    """
    Envoie au client un SMS contenant le lien d’utilisation de la récompense (token).
    POST /rewards/<pk>/send/sms/
    """
    reward = get_object_or_404(Reward.objects.select_related("client", "company"), pk=pk)

    # --- Permissions (mêmes règles que distribute_reward) ---
    user = request.user
    if not (_is_superadmin(user) or (getattr(user, "company_id", None) and reward.company_id == user.company_id)):
        raise Http404("Non autorisé")

    # Génère un token s’il n’existe pas encore (pour construire l’URL)
    reward.ensure_token()
    reward.save(update_fields=["token", "token_expires_at"])

    # Données pour le SMS
    claim_absolute = request.build_absolute_uri(reward.claim_path)
    client_fullname = f"{reward.client.first_name} {reward.client.last_name}".strip()
    company_name = (getattr(reward.company, "name", "") or "").strip() or None

    # ⚠️ normalize_msisdn renvoie (e164, meta) -> on déballe et on utilise e164
    to_e164, meta = normalize_msisdn(
        reward.client.phone or "",
        default_region=getattr(settings, "SMS_DEFAULT_REGION", "FR"),
    )
    if not to_e164:
        messages.error(request, "Le client n’a pas de numéro de téléphone valide.")
        back_id = request.POST.get("back_client")
        return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("dashboard:clients_list")

    text = build_reward_sms_text(
        client_fullname=client_fullname,
        claim_absolute_url=claim_absolute,
        company_name=company_name,
    )

    payload = SMSPayload(
        to=to_e164,
        text=text,
        sender=(settings.SMSMODE.get("SENDER") or None),
    )
    result = send_sms(payload)

    # Log utile pour debug (meta contient ce qu'a fait la normalisation)
    logger.warning("SMS SEND to=%s ok=%s status=%s meta=%s raw=%s",
                   to_e164, result.ok, result.status, meta, (result.raw or {}))

    if result.ok:
        messages.success(request, "SMS envoyé au client.")
    else:
        messages.error(request, f"Échec d’envoi SMS ({result.status}).")

    back_id = request.POST.get("back_client")
    return redirect("dashboard:client_detail", pk=back_id) if back_id else redirect("rewards:history_company")
@login_required
def validate_referral_and_award_referrer(request, referral_id: int):
    """
    Valide un parrainage et attribue une récompense au PARRAIN ET au FILLEUL.

    -> Respecte maintenant les minimums de parrainages configurés sur les RewardTemplate.
    """
    referral = get_object_or_404(
        Referral.objects.select_related("company", "referrer", "referee"), pk=referral_id
    )
    company: Company = referral.company

    user = request.user
    if not (_is_superadmin(user) or getattr(user, "company_id", None) == company.id):
        messages.error(request, "Accès refusé.")
        return redirect("dashboard:client_detail", pk=referral.referrer_id)

    reward_parrain, reward_filleul = award_both_parties(referral=referral)

    if reward_parrain is None:
        messages.success(
            request,
            (
                f"Parrainage validé. Récompense créée pour le filleul « {reward_filleul.label} ». "
                "Le parrain n'a pas encore atteint le minimum requis pour obtenir un cadeau."
            ),
        )
    else:
        messages.success(
            request,
            (
                f"Parrainage validé. Récompenses créées : Parrain « {reward_parrain.label} » "
                f"et Filleul « {reward_filleul.label} »."
            ),
        )

    return redirect("dashboard:client_detail", pk=referral.referrer_id)
