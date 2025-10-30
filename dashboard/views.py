# dashboard/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from django.utils import timezone

from accounts.models import Company
from dashboard.models import Client, Referral
from .forms import (
    ReferrerClientForm,
    RefereeClientForm,
    ReferralForm,
    RefereeInlineForm,
)
from rewards.forms import RewardTemplateForm
from rewards.models import Reward, RewardTemplate
from rewards.services import award_both_parties
from accounts.utils import skip_client_user_autocreate

# -------------------------------------------------------------
# Helpers (rôles & périmètre)
# -------------------------------------------------------------
def _is_superadmin(u) -> bool:
    # OK si superuser Django OU rôle métier "superadmin"
    return getattr(u, "is_superuser", False) or (hasattr(u, "is_superadmin") and u.is_superadmin())


def _is_company_admin(u) -> bool:
    return hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise()

def _is_operator(u) -> bool:
    return hasattr(u, "is_operateur") and u.is_operateur()

def _require_company_staff(user):
    if _is_superadmin(user) or _is_company_admin(user) or _is_operator(user):
        return
    raise PermissionDenied("Accès réservé au personnel.")

def _company_for(user):
    # Admin/Opérateur : l’entreprise de l’utilisateur
    # Superadmin : à choisir via l’UI (ou None ici)
    return getattr(user, "company", None)


def _promote_to_referrer(client: Client) -> bool:
    """Passe un client en parrain si ce n'est pas déjà le cas."""
    if not client or getattr(client, "is_referrer", None) is True:
        return False
    # update atomique et idempotent
    updated = Client.objects.filter(pk=client.pk, is_referrer=False).update(is_referrer=True)
    if updated:
        client.is_referrer = True
        return True
    return False

# -------------------------------------------------------------
# KPI / activité pour tableaux de bord
# -------------------------------------------------------------
def _month_bounds(now=None):
    now = now or timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = month_start
    if month_start.month == 1:
        prev_month_start = month_start.replace(year=month_start.year - 1, month=12)
    else:
        prev_month_start = month_start.replace(month=month_start.month - 1)
    return month_start, prev_month_start, prev_month_end

def _kpis_for_company(company: Company):
    now = timezone.now()
    month_start, prev_month_start, prev_month_end = _month_bounds(now)

    referrals_this_month = Referral.objects.filter(
        company=company, created_at__gte=month_start
    ).count()

    prev_referrals = Referral.objects.filter(
        company=company, created_at__gte=prev_month_start, created_at__lt=prev_month_end
    ).count()

    delta_pct = 0
    if prev_referrals:
        delta_pct = round((referrals_this_month - prev_referrals) * 100 / prev_referrals)

    return {
        "referrals_month": referrals_this_month,
        "referrals_delta_pct": delta_pct,
        "rewards_sent": Reward.objects.filter(company=company, state="SENT").count(),
        "rewards_pending": Reward.objects.filter(company=company, state="PENDING").count(),
        "clients": Client.objects.filter(company=company).count(),
    }

def _recent_events_for_company(company: Company, limit=8):
    events = []

    for r in (
        Referral.objects.select_related("referrer", "referee")
        .filter(company=company)
        .order_by("-created_at")[:limit]
    ):
        events.append(
            {
                "icon": "👥",
                "text": f"Parrainage validé — {r.referrer.last_name} {r.referrer.first_name} → "
                        f"{r.referee.last_name} {r.referee.first_name}",
                "badge": "OK",
            }
        )

    pend = Reward.objects.filter(company=company, state="PENDING").count()
    if pend:
        events.append(
            {"icon": "🎁", "text": "Cadeau en attente — Envoyer le lien au parrain", "badge": str(pend)}
        )

    events.append({"icon": "🧑", "text": "Base clients — total à jour", "badge": "+1"})
    return events[:limit]

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

    companies = Company.objects.all().order_by("name")

    totals = {"referrals_month": 0, "rewards_sent": 0, "rewards_pending": 0, "clients": 0}
    rows = []

    for c in companies:
        k = _kpis_for_company(c)
        rows.append(
            {
                "company": c,
                "referrals_month": k["referrals_month"],
                "rewards_sent": k["rewards_sent"],
                "rewards_pending": k["rewards_pending"],
                "clients": k["clients"],
            }
        )
        totals["referrals_month"] += k["referrals_month"]
        totals["rewards_sent"] += k["rewards_sent"]
        totals["rewards_pending"] += k["rewards_pending"]
        totals["clients"] += k["clients"]

    events = []  # (optionnel) activité globale
    return render(
        request,
        "dashboard/superadmin_home.html",
        {"kpi": totals, "events": events, "rows": rows},
    )

@login_required
def company_home(request):
    u = request.user
    if not (_is_superadmin(u) or _is_company_admin(u) or _is_operator(u)):
        raise PermissionDenied("Réservé à l’Admin/Opérateur (ou Superadmin).")

    # valeur par défaut : l’entreprise de l’utilisateur
    company = _company_for(u)  # admin/opérateur -> user.company

    # superadmin peut cibler une entreprise via ?company=<id>
    if _is_superadmin(u):
        cid = (request.GET.get("company") or "").strip()
        if cid:
            company = get_object_or_404(Company, pk=cid)
            # request.session["dash_company_id"] = company.id

    if not company:
        messages.info(request, "Sélectionnez une entreprise.")
        return redirect("accounts:company_list")

    kpi = _kpis_for_company(company)
    events = _recent_events_for_company(company)
    return render(
        request,
        "dashboard/company_home.html",
        {"company": company, "kpi": kpi, "events": events},
    )

# -------------------------------------------------------------
# Clients : liste / détail
# -------------------------------------------------------------
@login_required
def clients_list(request):
    """
    Liste des PARRAINS (clients is_referrer=True) de l'entreprise courante
    (ou de toutes si superadmin). Affiche une popup d'award si présente
    dans la session (après création d’un parrainage).
    """
    _require_company_staff(request.user)

    # Récupère et consomme la popup éventuelle (parrainage créé)
    award_popup = request.session.pop("award_popup", None)

    u = request.user
    qs = Client.objects.filter(is_referrer=True)
    if not _is_superadmin(u):
        qs = qs.filter(company=u.company)

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(email__icontains=q)
        )

    qs = qs.order_by("last_name", "first_name")

    return render(
        request,
        "dashboard/clients_list.html",
        {
            "clients": qs,
            "filter_type": "parrains",
            "current_q": q,
            "award_popup": award_popup,  # <-- important
        },
    )


@login_required
def client_detail(request, pk: int):
    _require_company_staff(request.user)

    u = request.user
    if _is_superadmin(u):
        client = get_object_or_404(Client.objects.select_related("company"), pk=pk)
    else:
        client = get_object_or_404(
            Client.objects.select_related("company"), pk=pk, company=u.company
        )

    # Historique des parrainages (où ce client est parrain OU filleul)
    history_qs = (
        Referral.objects.select_related("referrer", "referee")
        .filter(company=client.company)
        .filter(Q(referrer=client) | Q(referee=client))
        .order_by("-created_at", "-id")
    )
    history_page = Paginator(history_qs, 8).get_page(request.GET.get("h"))

    # Map referral_id -> reward_id (récompense de ce client liée à ce parrainage)
    ref_ids = [r.id for r in history_page.object_list]
    rewards_for_rows = (
        Reward.objects.filter(company=client.company, client=client, referral_id__in=ref_ids)
        .exclude(state="DISABLED")
        .values_list("referral_id", "id")
    )
    ref_rewards = {ref_id: reward_id for ref_id, reward_id in rewards_for_rows}
    for r in history_page.object_list:
        r.existing_reward_id = ref_rewards.get(r.id)

    # Récompenses par statut (3 colonnes)
    rewards_ok = (
        Reward.objects.filter(company=client.company, client=client, state="SENT").order_by("-id")
    )
    rewards_pending = (
        Reward.objects.filter(company=client.company, client=client, state="PENDING").order_by("-id")
    )
    rewards_unused = (
        Reward.objects.filter(company=client.company, client=client, state="DISABLED").order_by("-id")
    )

    page_ok = Paginator(rewards_ok, 5).get_page(request.GET.get("ok"))
    page_pending = Paginator(rewards_pending, 5).get_page(request.GET.get("pending"))
    page_unused = Paginator(rewards_unused, 5).get_page(request.GET.get("unused"))

    return render(
        request,
        "dashboard/client_detail.html",
        {
            "company": client.company,
            "client": client,
            "history_page": history_page,
            "page_ok": page_ok,
            "page_pending": page_pending,
            "page_unused": page_unused,
            "kpi_obtenus": rewards_ok.count(),
            "kpi_attente": rewards_pending.count(),
            "kpi_nonutils": rewards_unused.count(),
        },
    )
    
from django.conf import settings
from django.core.mail import send_mail

# -------------------------------------------------------------
# Clients : création / édition / suppression
# -------------------------------------------------------------
@login_required
@transaction.atomic
def client_update(request, pk: int):
    """
    Éditer un client (parrain OU filleul).
    Choix automatique du bon formulaire et verrouillage du périmètre.
    """
    _require_company_staff(request.user)

    qs = Client.objects.select_related("company")
    obj = (
        get_object_or_404(qs, pk=pk)
        if _is_superadmin(request.user)
        else get_object_or_404(qs, pk=pk, company=request.user.company)
    )

    is_ref = bool(obj.is_referrer)
    FormCls = ReferrerClientForm if is_ref else RefereeClientForm
    template = "dashboard/referrer_form.html" if is_ref else "dashboard/referee_form.html"

    form = FormCls(request.POST or None, instance=obj, request=request)

    if not _is_superadmin(request.user) and "company" in form.fields:
        form.fields["company"].disabled = True

    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        c.is_referrer = True if is_ref else False
        if not _is_superadmin(request.user):
            c.company = request.user.company
        try:
            c.save()
        except IntegrityError:
            if is_ref:
                form.add_error(
                    "last_name",
                    "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.",
                )
            else:
                form.add_error(None, "Conflit d’unicité détecté pour ce client.")
        else:
            messages.success(request, "Client mis à jour.")
            return redirect("dashboard:clients_list")

    return render(
        request,
        template,
        {"form": form, "referrer": obj if is_ref else None, "is_update": True},
    )

@login_required
def client_delete(request, pk: int):
    _require_company_staff(request.user)

    obj = get_object_or_404(Client, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Client supprimé.")
        return redirect("dashboard:clients_list")

    return render(
        request,
        "dashboard/confirm_delete.html",
        {
            "title": "Supprimer le client",
            "message": f"Supprimer définitivement {obj.last_name} {obj.first_name} ?",
            "post_action": "dashboard:client_delete",
            "post_kwargs": {"pk": obj.pk},
            "back_url_name": "dashboard:clients_list",
            "back_url_kwargs": {},
        },
    )

# -------------------------------------------------------------
# Parrains : CRUD + API recherche
# -------------------------------------------------------------


@login_required
def referrer_create(request):
    _require_company_staff(request.user)
    form = ReferrerClientForm(request.POST or None, request=request)

    if request.method == "POST" and form.is_valid():
        try:
            ref = form.save(commit=False)  # force is_referrer=True dans le form
            if not _is_superadmin(request.user):
                ref.company = request.user.company
            ref.save()  # ← sauvegarde dans tous les cas
        except IntegrityError:
            form.add_error(
                "last_name",
                "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.",
            )
        else:
            messages.success(request, "Parrain créé avec succès.")
            return redirect("dashboard:clients_list")

    return render(request, "dashboard/referrer_form.html", {"form": form})




@login_required
def referrer_update(request, pk: int):
    """
    Modifier un PARRAIN (is_referrer=True) avec les mêmes règles de périmètre.
    """
    _require_company_staff(request.user)

    base_qs = Client.objects.select_related("company").filter(is_referrer=True)
    obj = (
        get_object_or_404(base_qs, pk=pk)
        if _is_superadmin(request.user)
        else get_object_or_404(base_qs, pk=pk, company=request.user.company)
    )

    form = ReferrerClientForm(request.POST or None, instance=obj, request=request)

    if request.method == "POST" and form.is_valid():
        try:
            ref = form.save(commit=False)
            ref.is_referrer = True
            if not _is_superadmin(request.user):
                ref.company = request.user.company
            ref.save()
        except IntegrityError:
            form.add_error(
                "last_name",
                "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.",
            )
        else:
            messages.success(request, "Parrain modifié avec succès.")
            return redirect("dashboard:clients_list")

    return render(
        request, "dashboard/referrer_form.html", {"form": form, "referrer": obj, "is_update": True}
    )

@login_required
def referrer_lookup(request):
    """
    API JSON pour l’autocomplete des parrains.
    """
    _require_company_staff(request.user)

    q = (request.GET.get("q") or "").strip()
    id_param = request.GET.get("id")
    company_id = request.GET.get("company_id")

    qs = Client.objects.filter(is_referrer=True).select_related("company")

    if _is_superadmin(request.user):
        if company_id:
            qs = qs.filter(company_id=company_id)
    else:
        qs = qs.filter(company=request.user.company)

    if id_param:
        obj = qs.filter(pk=id_param).first()
        if not obj:
            from django.http import JsonResponse

            return JsonResponse({"ok": False, "error": "not_found"}, status=404)
        label = f"{obj.last_name} {obj.first_name}".strip() or (obj.email or "—")
        label += f" — {obj.email or '—'} ({obj.company.name if obj.company else '—'})"
        label += f" — {obj.phone or '—'}"
        return JsonResponse({"ok": True, "result": {"id": obj.id, "label": label}})

    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(email__icontains=q) |
            Q(phone__icontains=q)
        )

    qs = qs.order_by("last_name", "first_name")[:20]

    def to_item(o):
        label = f"{o.last_name} {o.first_name}".strip() or (o.email or o.phone or "—")
        label += f" — {o.email or '—'}"
        label += f" — {o.phone or '—'}"
        label += f" ({o.company.name if o.company else '—'})"
        return {"id": o.id, "label": label}

    from django.http import JsonResponse

    return JsonResponse({"ok": True, "results": [to_item(o) for o in qs]})

# -------------------------------------------------------------
# Parrainage : création (recherche parrain + filleul inline)
# -------------------------------------------------------------
@login_required
@transaction.atomic
def referral_create(request, company_id=None):
    """
    1) Sélection d’un parrain via autocomplete,
    2) Saisie/repérage du filleul (création si besoin dans l’entreprise du parrain),
    3) Création du parrainage + 2 récompenses (parrain & filleul),
       -> la récompense du FILLEUL est immédiatement marquée 'SENT' (distribuée),
          celle du PARRAIN reste 'PENDING',
       puis envoi automatique du lien au FILLEUL si possible.
    """
    # ---- Contexte entreprise pour l’autocomplete ----
    if _is_superadmin(request.user) and company_id:
        company_ctx = Company.objects.filter(pk=company_id).first()
    else:
        company_ctx = getattr(request.user, "company", None)

    ref_form = RefereeInlineForm(request.POST or None)
    referrer_error = None

    if request.method == "POST":
        # Parrain choisi (ID venant du champ caché)
        raw_referrer_id = (request.POST.get("referrer") or "").strip()

        referrer_qs = Client.objects.filter(is_referrer=True).select_related("company")
        if not _is_superadmin(request.user):
            referrer_qs = referrer_qs.filter(company=request.user.company)

        referrer = None
        if raw_referrer_id:
            try:
                referrer = referrer_qs.filter(pk=int(raw_referrer_id)).first()
            except (TypeError, ValueError):
                referrer = None

        if not referrer:
            referrer_error = "Sélectionnez un parrain valide dans la liste."
        elif ref_form.is_valid():
            # Créer / réutiliser le filleul dans l’entreprise du parrain
            company = referrer.company
            email = (ref_form.cleaned_data.get("email") or "").strip().lower()
            referee = (
                Client.objects.filter(company=company, email__iexact=email).first()
                if email else None
            )
            if referee is None:
                referee = ref_form.save_with_company(company)

            # Création du parrainage (valide les cohérences via ReferralForm)
            rf = ReferralForm(
                data={"referrer": referrer.pk, "referee": referee.pk},
                request=request,
                company=company,
            )
            if rf.is_valid():
                referral = rf.save(commit=False)
                referral.company = company
                try:
                    referral.save()
                except IntegrityError:
                    ref_form.add_error(None, "Ce filleul a déjà un parrainage dans cette entreprise.")
                else:
                    # Crée les 2 récompenses — idempotent par (company, client, referral)
                    reward_parrain, reward_filleul = award_both_parties(referral=referral)

                    # --- Sécurise : identifie quelle reward appartient à qui ---
                    rw_referrer = reward_parrain
                    rw_referee = reward_filleul
                    for rw in (reward_parrain, reward_filleul):
                        if rw.client_id == referrer.id:
                            rw_referrer = rw
                        elif rw.client_id == referee.id:
                            rw_referee = rw

                    # ✅ Le FILLEUL reçoit immédiatement (SENT)
                    if getattr(rw_referee, "state", None) != "SENT":
                        rw_referee.state = "SENT"
                        update_fields = ["state"]
                        if hasattr(rw_referee, "sent_at") and not getattr(rw_referee, "sent_at", None):
                            rw_referee.sent_at = timezone.now()
                            update_fields.append("sent_at")
                        rw_referee.save(update_fields=update_fields)
                        _promote_to_referrer(referee)


                    # ✅ Alimente la popup (affichée à l'arrivée sur clients_list)
                    request.session["award_popup"] = {
                        "referrer_name": f"{referrer.first_name} {referrer.last_name}".strip() or str(referrer),
                        "referee_name": f"{referee.first_name} {referee.last_name}".strip() or str(referee),
                        "referrer_label": getattr(rw_referrer, "label", "—"),
                        "referee_label": getattr(rw_referee, "label", "—"),
                    }

                    messages.success(
                        request,
                        f"Parrainage créé : {referrer} → {referee}. "
                        f"Récompenses : Parrain « {rw_referrer.label} » (en attente) "
                        f"et Filleul « {rw_referee.label} » (envoyée).",
                    )

                    claim_referrer_abs = (
                        request.build_absolute_uri(rw_referrer.claim_path)
                        if getattr(rw_referrer, "claim_path", "")
                        else ""
                    )
                                        
                    def _email_parrain_after_commit():
                        try:
                            to_email = (referrer.email or "").strip()
                            if not to_email:
                                messages.info(request, "Parrainage OK, mais e-mail du parrain introuvable — email non envoyé.")
                                return  # pas d'email → on n'envoie pas

                            company_name = getattr(company, "name", "Votre enseigne")
                            prenom = (referrer.first_name or referrer.last_name or str(referrer)).strip()
                            filleul_prenom = (referee.first_name or referee.last_name or str(referee)).strip()
                            lien_cadeau = (claim_referrer_abs or "").strip()

                            subject = f"{company_name} – parrainage validé 🎉"

                            body_lines = [
                                "⸻",
                                "",
                                f"Bonjour {prenom},",
                                "",
                                f"{filleul_prenom} est venu découvrir {company_name} grâce à toi 💛",
                                "",
                                f"Et comme chez {company_name}, on aime remercier ceux qui partagent leurs bonnes adresses…",
                                "ton parrainage vient d’être validé 🎉",
                                "",
                                "En remerciement, tu remportes un cadeau 🎁",
                            ]
                            if lien_cadeau:
                                body_lines += [f"Découvre-le en cliquant [ici]({lien_cadeau})."]

                            body_lines += [
                                "",
                                f"Merci encore d’avoir parlé de {company_name} autour de toi —",
                                "c’est grâce à des clients comme toi qu’on fait ce métier avec passion 💛",
                                "",
                                "À très vite,",
                                f"L’équipe {company_name}",
                                "",
                                "⸻",
                                "",
                                f"✉️ Ce message t’a été envoyé par {company_name} via Chuchote,",
                                "le service qui facilite la gestion des parrainages clients.",
                            ]

                            body = "\n".join(body_lines)

                            sent = send_mail(
                                subject=subject,
                                message=body,
                                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                                recipient_list=[to_email],
                                fail_silently=False,
                            )
                            if not sent:
                                messages.warning(request, "Parrainage OK, mais l’e-mail n’a pas été accepté par le backend (send_mail=0).")
                        except Exception as e:
                            messages.warning(request, f"Parrainage OK, email au parrain non envoyé : {e}")

                    # IMPORTANT : conserver cet appel APRÈS la définition
                    transaction.on_commit(_email_parrain_after_commit)


                    # IMPORTANT : déclencher l'envoi APRÈS le commit de la transaction
                    transaction.on_commit(_email_parrain_after_commit)
                    if referee.phone and claim_referrer_abs:
                        # Envoi différé après commit (SMS via SMSMODE)
                        def _after_commit():
                            import os, json
                            import requests
                            from django.conf import settings

                            try:
                                conf = getattr(settings, "SMSMODE", {})
                                api_key  = conf.get("API_KEY") or os.getenv("SMSMODE_API_KEY", "")
                                base_url = (conf.get("BASE_URL") or "https://rest.smsmode.com").rstrip("/")
                                sender   = (conf.get("SENDER") or "ParrainApp").strip()
                                dry_run  = bool(conf.get("DRY_RUN"))
                                timeout  = int(conf.get("TIMEOUT", 10))

                                if not api_key:
                                    messages.info(request, "Parrainage OK. SMS non envoyé (SMSMODE_API_KEY manquant).")
                                    return

                                # Normalise le numéro: garde chiffres et '+' puis retire le '+' (SMSMODE attend 336..., pas +336)
                                raw = "".join(ch for ch in (referee.phone or "") if ch.isdigit() or ch == "+")
                                to_number = raw.lstrip("+")

                                text = f"{referee.first_name or referee.last_name}, voici votre lien cadeau : {claim_referrer_abs}"

                                payload = {
                                    "recipient": {"to": to_number},
                                    "body": {"text": text},
                                    "from": sender,
                                }
                                headers = {
                                    "X-Api-Key": api_key,
                                    "Content-Type": "application/json",
                                    "Accept": "application/json",
                                }
                                url = f"{base_url}/sms/v1/messages"

                                if dry_run:
                                    messages.info(request, f"DRY_RUN SMSMODE → {to_number}: {text}")
                                    return

                                r = requests.post(url, headers=headers, json=payload, timeout=timeout)

                                if r.status_code in (200, 201, 202):
                                    messages.success(request, "Lien de récompense envoyé au filleul par SMS.")
                                else:
                                    messages.warning(
                                        request,
                                        f"Parrainage OK. SMS non envoyé ({r.status_code}) : {r.text[:300]}"
                                    )
                            except Exception as e:
                                messages.warning(request, f"Parrainage OK, SMS non envoyé : {e}")

                        transaction.on_commit(_after_commit)
                    else:
                        messages.info(request, "Parrainage OK. SMS non envoyé (numéro du filleul ou lien manquant).")


                    return redirect("dashboard:clients_list")
            else:
                err = rf.errors.get("referee")
                if err:
                    ref_form.add_error(None, err.as_text().replace("* ", ""))
                else:
                    messages.error(request, "Le parrainage n'a pas pu être créé. Corrigez les erreurs.")

    return render(
        request,
        "dashboard/referral_form.html",
        {"ref_form": ref_form, "referrer_error": referrer_error, "company": company_ctx},
    )



# -------------------------------------------------------------
# Parrainage : édition / suppression
# -------------------------------------------------------------
@login_required
def referral_update(request, pk: int):
    _require_company_staff(request.user)

    obj = get_object_or_404(Referral, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    current_company = None if _is_superadmin(request.user) else request.user.company

    if request.method == "POST":
        form = ReferralForm(request.POST, instance=obj, request=request, company=current_company)
        if form.is_valid():
            r = form.save(commit=False)
            r.company = r.referrer.company
            r.save()
            messages.success(request, "Parrainage mis à jour.")
            return redirect("dashboard:clients_list")
    else:
        form = ReferralForm(instance=obj, request=request, company=current_company)

    return render(request, "dashboard/referral_form.html", {"form": form})

@login_required
def referral_delete(request, pk: int):
    """
    Supprime un parrainage.
    Si back_client est fourni, retour à la fiche client, sinon à la liste des clients.
    """
    _require_company_staff(request.user)

    obj = get_object_or_404(Referral, pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != getattr(request.user, "company_id", None):
        raise PermissionDenied("Accès refusé.")

    back_client_id = request.POST.get("back_client") or request.GET.get("back_client")
    back_url_name = "dashboard:client_detail" if back_client_id else "dashboard:clients_list"
    back_url_kwargs = {"pk": back_client_id} if back_client_id else {}

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Parrainage supprimé.")
        return redirect(back_url_name, **back_url_kwargs)

    return render(
        request,
        "dashboard/confirm_delete.html",
        {
            "title": "Supprimer le parrainage",
            "message": "Confirmer la suppression de ce parrainage ?",
            "post_action": "dashboard:referral_delete",
            "post_kwargs": {"pk": obj.pk},
            "back_url_name": back_url_name,
            "back_url_kwargs": back_url_kwargs,
            "back_client_id": back_client_id,
        },
    )

# -------------------------------------------------------------
# Récompenses : création manuelle + validations
# -------------------------------------------------------------
@login_required
def reward_create(request, pk: int):
    """
    Création manuelle d’une Reward pour un client.
    """
    _require_company_staff(request.user)

    u = request.user
    client = get_object_or_404(
        Client, pk=pk, **({} if _is_superadmin(u) else {"company": u.company})
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
    Valide un parrainage et attribue une récompense au FILLEUL,
    puis redirige vers l’animation de tirage.
    """
    _require_company_staff(request.user)

    referral = get_object_or_404(
        Referral.objects.select_related("referee", "referrer", "company"), pk=referral_id
    )

    user_company = _company_for(request.user)
    if user_company and referral.company_id != user_company.id and not _is_superadmin(request.user):
        messages.error(request, "Ce parrainage n’appartient pas à votre entreprise.")
        return redirect("dashboard:clients_list")

    client = referral.referee
    # Exemple: tirage exact via un bucket/token déjà configuré (adapter si nécessaire)
    # Ici on clone simplement un template au même bucket
    token = RewardTemplate.objects.filter(company=referral.company).first().bucket  # (à adapter)
    tpl = get_object_or_404(RewardTemplate, company=referral.company, bucket=token)

    reward = Reward.objects.create(
        company=referral.company,
        client=client,
        referral=referral,
        label=tpl.label,
        bucket=token,
        cooldown_days=tpl.cooldown_days,
        state="PENDING",
    )

    messages.success(
        request, f"Parrainage validé. Récompense pour le filleul « {client} » : {tpl.label}."
    )
    return redirect("rewards:spin", reward_id=reward.id)

@login_required
def validate_referral_and_award_referrer(request, referral_id: int):
    """
    Valide un parrainage et attribue une récompense au PARRAIN ET au FILLEUL.
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

    messages.success(
        request,
        f"Parrainage validé. Récompenses créées : Parrain « {reward_parrain.label} » "
        f"et Filleul « {reward_filleul.label} ».",
    )
    return redirect("dashboard:client_detail", pk=referral.referrer_id)

# --- AJOUTER EN BAS DU FICHIER (ou près des vues superadmin) ---

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse

# ...

@login_required
def superadmin_rewards(request):
    """
    Porte d’entrée Superadmin vers la gestion des récompenses.
    - Si ?company=<id> est fourni, redirige vers rewards:list avec ce périmètre.
    - Sinon, affiche une liste d’entreprises à choisir.
    """
    if not _is_superadmin(request.user):
        raise PermissionDenied("Réservé au Superadmin.")

    cid = (request.GET.get("company") or "").strip()
    if cid:
        # Redirige vers la liste des récompenses du module rewards, en conservant le périmètre entreprise
        url = reverse("rewards:list")
        return redirect(f"{url}?company={cid}")

    companies = Company.objects.all().order_by("name")
    return render(request, "dashboard/superadmin_rewards_entry.html", {"companies": companies})


@login_required
def superadmin_stats(request):
    """
    Statistiques globales (toutes entreprises) pour le Superadmin.
    Affiche les KPI par entreprise + totaux agrégés.
    """
    if not _is_superadmin(request.user):
        raise PermissionDenied("Réservé au Superadmin.")

    companies = Company.objects.all().order_by("name")

    totals = {"referrals_month": 0, "rewards_sent": 0, "rewards_pending": 0, "clients": 0}
    rows = []
    for c in companies:
        k = _kpis_for_company(c)
        rows.append({
            "company": c,
            "referrals_month": k["referrals_month"],
            "rewards_sent": k["rewards_sent"],
            "rewards_pending": k["rewards_pending"],
            "clients": k["clients"],
        })
        totals["referrals_month"] += k["referrals_month"]
        totals["rewards_sent"] += k["rewards_sent"]
        totals["rewards_pending"] += k["rewards_pending"]
        totals["clients"] += k["clients"]

    return render(
        request,
        "dashboard/superadmin_stats.html",
        {"kpi": totals, "rows": rows},
    )
