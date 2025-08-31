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
from .forms import ReferrerClientForm, RefereeClientForm, ReferralForm, RefereeInlineForm
from rewards.models import Reward, RewardTemplate
from rewards.forms import RewardTemplateForm

from rewards.notifications.services import send_sms
from rewards.models import RewardTemplate, Reward

# Tirage de récompense
from rewards.services.probabilities import tirer_recompense, SOUVENT, MOYEN, RARE, TRES_RARE
from django.db import transaction

import os
from twilio.rest import Client as TwilioClient


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


from .forms import ReferrerClientForm, RefereeClientForm, ReferralForm, RefereeInlineForm
from django.http import JsonResponse

from django.db import transaction
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db import IntegrityError
from django.db.models import Q



@login_required
@transaction.atomic
def client_update(request, pk: int):
    """
    Éditer un client (parrain OU filleul).
    - Sélectionne automatiquement le bon form et le bon template.
    - Verrouille company côté non-superadmin.
    - Anti-doublon parrain via IntegrityError (contrainte BD + clean du form).
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

    # UX : champ company désactivé pour non-superadmin (cohérent avec le verrou au save)
    if not _is_superadmin(request.user) and "company" in form.fields:
        form.fields["company"].disabled = True

    if request.method == "POST" and form.is_valid():
        c = form.save(commit=False)
        # on fige le type de client
        c.is_referrer = True if is_ref else False
        # côté non-superadmin, on fige l’entreprise
        if not _is_superadmin(request.user):
            c.company = request.user.company
        try:
            c.save()
        except IntegrityError:
            if is_ref:
                form.add_error("last_name", "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.")
            else:
                form.add_error(None, "Conflit d’unicité détecté pour ce client.")
        else:
            messages.success(request, "Client mis à jour.")
            return redirect("dashboard:clients_list")

    return render(request, template, {
        "form": form,
        "referrer": obj if is_ref else None,
        "is_update": True,
    })
    
    
# dashboard/views.py

try:
    import phonenumbers
    from phonenumbers import PhoneNumberFormat
    _HAS_PHONENUMBERS = True
except Exception:
    _HAS_PHONENUMBERS = False

from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from accounts.models import Company
from dashboard.models import Client, Referral
from .forms import RefereeInlineForm, ReferralForm
from rewards.models import RewardTemplate, Reward
from rewards.services.probabilities import tirer_recompense


@login_required
@transaction.atomic
def referral_create(request, company_id=None):
    """
    Choisir un parrain (autocomplete) + créer le FILLEUL inline,
    puis créer le parrainage. Le filleul est toujours dans l’entreprise du parrain.

    Après création, on crée une Reward PENDING pour le PARRAIN, on génère
    un lien (token) et on l’envoie automatiquement par SMS (Twilio).
    """
    import os

    # ---------- Helpers SMS ----------
    def _normalize_to_e164(phone: str) -> str | None:
        """
        Retourne un numéro au format +E164 pour SMS Twilio si possible, sinon None.
        Accepte pratiquement tous les formats (espaces, parenthèses, 0 initial, etc.).
        Utilise libphonenumbers si disponible, sinon heuristique sûre.
        """
        if not phone:
            return None
        raw = str(phone).strip()
        cleaned = "".join(ch for ch in raw if ch.isdigit() or ch == "+")
        if not cleaned:
            return None

        default_region = (os.getenv("DEFAULT_PHONE_REGION") or "FR").upper()

        # 1) libphonenumbers si dispo (précis)
        try:
            import phonenumbers
            from phonenumbers import PhoneNumberFormat
            parsed = phonenumbers.parse(cleaned, None if cleaned.startswith("+") else default_region)
            if phonenumbers.is_possible_number(parsed) and phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        except Exception:
            pass

        # 2) Heuristique de repli
        digits = "".join(ch for ch in cleaned if ch.isdigit())
        if cleaned.startswith("+"):
            # +XXXXXXXXX
            return f"+{digits}" if 8 <= len(digits) <= 15 else None

        # suppose déjà indicatif (ex: 201507205488) => +201507205488
        if len(digits) >= 11 and not digits.startswith("0"):
            return f"+{digits}"

        # 0XXXXXXXXX => remplace 0 par indicatif régional
        if digits.startswith("0"):
            CC = {
                "FR": "+33", "US": "+1",  "GB": "+44", "DE": "+49", "ES": "+34", "IT": "+39",
                "BE": "+32", "NL": "+31", "CH": "+41", "CA": "+1",  "MA": "+212","DZ": "+213",
                "TN": "+216","SN": "+221","CI": "+225","CM": "+237","BF": "+226","BJ": "+229",
                "TG": "+228","ML": "+223","NE": "+227","PT": "+351","RO": "+40","EG": "+20"
            }
            cc = CC.get(default_region, "")
            return f"{cc}{digits[1:]}" if cc else None

        # Dernier recours
        return f"+{digits}" if digits else None

    def _send_sms(to_e164: str, body: str) -> tuple[bool, str | None]:
        """
        Envoi SMS via Twilio. Variables d'env requises :
          - TWILIO_ACCOUNT_SID
          - TWILIO_AUTH_TOKEN
          - TWILIO_SMS_FROM (ex: '+14155550123')
        """
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        sender = os.getenv("TWILIO_SMS_FROM")
        if not (sid and token and sender):
            return False, "Configuration Twilio manquante (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_SMS_FROM)."
        try:
            from twilio.rest import Client as TwilioClient
        except Exception as e:
            return False, f"Lib Twilio introuvable ou invalide : {e}"
        try:
            cli = TwilioClient(sid, token)
            cli.messages.create(to=to_e164, from_=sender, body=body)
            return True, None
        except Exception as e:
            return False, str(e)

    # ---------- Contexte entreprise pour l'autocomplete ----------
    if hasattr(request.user, "is_superadmin") and request.user.is_superadmin() and company_id:
        company_ctx = Company.objects.filter(pk=company_id).first()
    else:
        company_ctx = getattr(request.user, "company", None)

    ref_form = RefereeInlineForm(request.POST or None)
    referrer_error = None

    if request.method == "POST":
        # 1) PARRAIN choisi via l'autocomplete
        raw_referrer_id = (request.POST.get("referrer") or "").strip()

        referrer_qs = Client.objects.filter(is_referrer=True).select_related("company")
        if not (hasattr(request.user, "is_superadmin") and request.user.is_superadmin()):
            referrer_qs = referrer_qs.filter(company=request.user.company)

        referrer = None
        if raw_referrer_id:
            try:
                ref_id = int(raw_referrer_id)
                referrer = referrer_qs.filter(pk=ref_id).first()
            except (TypeError, ValueError):
                referrer = None

        if not referrer:
            referrer_error = "Sélectionnez un parrain valide dans la liste."
        elif ref_form.is_valid():
            # 2) Créer / réutiliser le FILLEUL dans l’entreprise du parrain
            company = referrer.company
            email = (ref_form.cleaned_data.get("email") or "").strip().lower()

            referee = Client.objects.filter(company=company, email__iexact=email).first() if email else None
            if referee is None:
                referee = ref_form.save_with_company(company)

            # 3) Créer le PARRAINAGE (avec validations du ReferralForm)
            rf = ReferralForm(
                data={"referrer": referrer.pk, "referee": referee.pk},
                request=request,
                company=company
            )
            if rf.is_valid():
                referral = rf.save(commit=False)
                referral.company = company
                try:
                    referral.save()
                except IntegrityError:
                    ref_form.add_error(None, "Ce filleul a déjà un parrainage dans cette entreprise.")
                else:
                    # 4) Reward PENDING pour le PARRAIN + lien + SMS auto
                    try:
                        from rewards.views import ensure_reward_templates
                        ensure_reward_templates(company)
                    except Exception:
                        pass

                    bucket_token = tirer_recompense(company)
                    tpl = get_object_or_404(RewardTemplate, company=company, bucket=bucket_token)

                    reward, _created = Reward.objects.get_or_create(
                        company=company,
                        client=referrer,       # bénéficiaire = PARRAIN
                        referral=referral,     # rattachement au parrainage
                        defaults={
                            "label": tpl.label,
                            "bucket": tpl.bucket,
                            "cooldown_days": tpl.cooldown_days,
                            "state": "PENDING",
                        },
                    )
                    reward.ensure_token(force=False)
                    reward.save(update_fields=["token", "token_expires_at"])

                    claim_abs = request.build_absolute_uri(reward.claim_path) if reward.claim_path else ""

                    messages.success(request, f"Parrainage créé : {referrer} → {referee}.")

                    # Envoi SMS après commit BDD
                    if referrer.phone and claim_abs:
                        to_e164 = _normalize_to_e164(referrer.phone)
                        sms_text = (
                            f"{referrer.first_name or referrer.last_name}, "
                            f"voici votre lien cadeau : {claim_abs}"
                        )

                        def _after_commit():
                            if to_e164:
                                ok, err = _send_sms(to_e164, sms_text)
                                if ok:
                                    messages.success(request, "Lien de récompense envoyé au parrain par SMS.")
                                else:
                                    messages.warning(request, f"Parrainage OK, SMS non envoyé : {err}")
                            else:
                                messages.info(request, "Parrainage OK. SMS non envoyé (numéro invalide).")

                        transaction.on_commit(_after_commit)
                    else:
                        messages.info(request, "Parrainage OK. SMS non envoyé (numéro du parrain ou lien manquant).")

                    # Redirection : fiche du PARRAIN
                    return redirect("dashboard:clients_list")
            else:
                err = rf.errors.get("referee")
                if err:
                    ref_form.add_error(None, err.as_text().replace("* ", ""))
                else:
                    messages.error(request, "Le parrainage n'a pas pu être créé. Corrigez les erreurs.")

    # GET ou erreurs : réaffiche le formulaire
    return render(
        request,
        "dashboard/referral_form.html",
        {"ref_form": ref_form, "referrer_error": referrer_error, "company": company_ctx},
    )


    
    
@login_required
def referrer_update(request, pk: int):
    """
    Modifier un PARRAIN (client is_referrer=True).
    - Non-superadmin : restriction à sa company et verrouillage de company au save.
    - Déduplique nom/prénom par entreprise (géré par le form + IntegrityError filet).
    """
    _require_company_staff(request.user)

    # Récupération sécurisée du parrain
    base_qs = Client.objects.select_related("company").filter(is_referrer=True)
    if _is_superadmin(request.user):
        obj = get_object_or_404(base_qs, pk=pk)
    else:
        obj = get_object_or_404(base_qs, pk=pk, company=request.user.company)

    form = ReferrerClientForm(request.POST or None, instance=obj, request=request)

    if request.method == "POST" and form.is_valid():
        try:
            ref = form.save(commit=False)
            # Empêche de “dé-parrainiser” et de changer d’entreprise côté non-superadmin
            ref.is_referrer = True
            if not _is_superadmin(request.user):
                ref.company = request.user.company
            ref.save()
        except IntegrityError:
            # Contrainte d’unicité BD (nom/prénom/entreprise) déclenchée
            form.add_error("last_name", "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise.")
        else:
            messages.success(request, "Parrain modifié avec succès.")
            return redirect("dashboard:clients_list")

    return render(
        request,
        "dashboard/referrer_form.html",
        {
            "form": form,
            "referrer": obj,
            "is_update": True,  # pour adapter le libellé dans le template
        },
    )


# dashboard/views.py
@login_required
def clients_list(request):
    _require_company_staff(request.user)

    u = request.user

    # ✅ UNIQUEMENT les parrains
    qs = Client.objects.filter(is_referrer=True)
    if not _is_superadmin(u):
        qs = qs.filter(company=u.company)

    # Recherche plein-texte (sur les parrains uniquement)
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
        "filter_type": "parrains",  # pour compat avec le template existant
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

    obj = get_object_or_404(Client.objects.select_related("company"), pk=pk)
    if not _is_superadmin(request.user) and obj.company_id != request.user.company_id:
        raise PermissionDenied("Accès refusé.")

    # Choix du formulaire et du template selon le type (parrain/filleul)
    is_ref = bool(obj.is_referrer)
    FormCls = ReferrerClientForm if is_ref else RefereeClientForm
    tpl = "dashboard/referrer_form.html" if is_ref else "dashboard/referee_form.html"

    if request.method == "POST":
        form = FormCls(request.POST, instance=obj, request=request)
        if form.is_valid():
            c = form.save(commit=False)
            if not _is_superadmin(request.user):
                c.company = request.user.company
            c.save()
            messages.success(request, "Client mis à jour.")
            return redirect("dashboard:clients_list")
    else:
        form = FormCls(instance=obj, request=request)

    return render(request, tpl, {"form": form})


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


# dashboard/views.py (ajoute ceci, près de tes autres vues)
from django.http import JsonResponse

@login_required
def referrer_lookup(request):
    """
    Retourne des parrains (JSON) selon une recherche 'q' (nom/prénom/email).
    - Non-superadmin : restreint à user.company
    - Superadmin : si company_id fourni => restreint, sinon global
    - Si 'id' fourni => renvoie 1 seul objet {id, label}
    """
    _require_company_staff(request.user)

    q = (request.GET.get("q") or "").strip()
    id_param = request.GET.get("id")
    company_id = request.GET.get("company_id")

    # Base QS (parrains uniquement)
    qs = Client.objects.filter(is_referrer=True).select_related("company")

    # Scope entreprise
    if _is_superadmin(request.user):
        if company_id:
            qs = qs.filter(company_id=company_id)
    else:
        qs = qs.filter(company=request.user.company)

    # Cherche par id direct (pour ré-afficher un libellé si déjà sélectionné)
    if id_param:
        obj = qs.filter(pk=id_param).first()
        if not obj:
            return JsonResponse({"ok": False, "error": "not_found"}, status=404)
        label = f"{obj.last_name} {obj.first_name}".strip() or (obj.email or "—")
        label += f" — {obj.email or '—'} ({obj.company.name if obj.company else '—'})"
        return JsonResponse({"ok": True, "result": {"id": obj.id, "label": label}})

    # Recherche textuelle
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(email__icontains=q)
        )

    qs = qs.order_by("last_name", "first_name")[:20]

    def to_item(o):
        label = f"{o.last_name} {o.first_name}".strip() or (o.email or "—")
        label += f" — {o.email or '—'} ({o.company.name if o.company else '—'})"
        return {"id": o.id, "label": label}

    return JsonResponse({"ok": True, "results": [to_item(o) for o in qs]})

@login_required
def referrer_create(request):
    """
    Créer un PARRAIN (client avec is_referrer=True).
    Superadmin choisit l'entreprise, sinon elle est forcée à user.company.
    """
    _require_company_staff(request.user)

    form = ReferrerClientForm(request.POST or None, request=request)

    if request.method == "POST" and form.is_valid():
        try:
            ref = form.save(commit=False)             # le form met déjà is_referrer=True
            if not _is_superadmin(request.user):      # verrou entreprise côté non-superadmin
                ref.company = request.user.company
            ref.save()
        except IntegrityError:
            form.add_error(
                "last_name",
                "Un parrain portant ce nom et ce prénom existe déjà dans cette entreprise."
            )
        else:
            messages.success(request, "Parrain créé avec succès.")
            return redirect("dashboard:clients_list")

    return render(request, "dashboard/referrer_form.html", {"form": form})