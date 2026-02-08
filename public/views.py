from __future__ import annotations

from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.core import signing
from django.core.mail import send_mail
from django.conf import settings
from django.views.decorators.http import require_POST
from django.contrib.auth import get_user_model

from accounts.models import Company
from dashboard.models import Client
from .forms import ReferrerForm, ReferrerResetForm
from rewards.models import RewardTemplate
from dashboard.forms import ReferrerPublicForm  # ✅
from django.db.models import Case, When, IntegerField
# ---------------------------
# Constantes / helpers
# ---------------------------

REFERRER_RESET_SALT = "referrer-profile-reset"
REFERRER_RESET_MAX_AGE = getattr(settings, "REFERRER_RESET_MAX_AGE", 3 * 24 * 3600)  # 3 jours

def _build_reset_link(request, *, client: Client) -> str:
    """
    Génère un lien signé (token) pour éditer le profil parrain (nom/prénom/téléphone).
    Le token embarque: cid, company_id, email — et expire côté verification.
    """
    payload = {
        "cid": client.pk,
        "company_id": client.company_id,
        "email": (client.email or "").strip().lower(),
    }
    token = signing.dumps(payload, salt=REFERRER_RESET_SALT)
    url = reverse("public:referrer_reset_edit", kwargs={"slug": client.company.slug, "token": token})
    return request.build_absolute_uri(url)

def _loads_token(token: str) -> dict:
    return signing.loads(token, max_age=REFERRER_RESET_MAX_AGE, salt=REFERRER_RESET_SALT)


def company_presentation(request, slug: str):
    company = get_object_or_404(Company, slug=slug)

    form = ReferrerPublicForm(company=company)

    reward_templates = (
    RewardTemplate.objects
    .filter(company=company)
    .annotate(
        bucket_order=Case(
            When(bucket="SOUVENT", then=0),
            When(bucket="MOYEN", then=1),
            When(bucket="RARE", then=2),
            When(bucket="TRES_RARE", then=3),
            default=99,
            output_field=IntegerField(),
        )
    )
    .order_by("bucket_order")
)


    return render(request, "public/landing_v2.html", {
        "company": company,
        "form": form,
        "reward_templates": reward_templates,
    })




def referrer_register(request, slug: str):
    company = get_object_or_404(Company, slug=slug)

    if request.method != "POST":
        return redirect("public:company_presentation", slug=slug)

    form = ReferrerPublicForm(request.POST, company=company)
    posted_email = (request.POST.get("email") or "").strip().lower()

    if form.is_valid():
        # ✅ garde ton contrôle email déjà utilisé (modale reset)
        already_referrer = bool(
            posted_email and Client.objects.filter(
                company=company, email__iexact=posted_email, is_referrer=True
            ).exists()
        )
        if already_referrer:
            form.add_error("email", "Cet email est déjà utilisé par un parrain de cette entreprise.")
            return render(request, "public/landing_v2.html", {
                "company": company,
                "form": form,
                "form_errors": True,
                "suggest_reset": True,
                "suggest_reset_email": posted_email,
                "open_register_modal": True,
            })

        try:
            with transaction.atomic():
                form.save()
        except IntegrityError as e:
            msg = str(e)

            # ✅ si la contrainte nom/prénom saute quand même
            if "uniq_referrer_name_per_company_ci" in msg:
                form.add_error("last_name", "Un parrain portant ce nom existe déjà pour cette entreprise.")
            else:
                form.add_error(None, "Impossible d’enregistrer. Vérifiez les informations.")

            return render(request, "public/landing_v2.html", {
                "company": company,
                "form": form,
                "form_errors": True,
                "open_register_modal": True,
            })

        messages.success(request, "✅ Inscription validée ! Vous êtes maintenant parrain.")
        return redirect("public:company_presentation", slug=slug)

    # ❌ form invalide → on ré-affiche + on ouvre la modale
    return render(request, "public/landing_v2.html", {
        "company": company,
        "form": form,
        "form_errors": True,
        "open_register_modal": True,
    })


@require_POST
def referrer_reset_request(request, slug: str):
    """
    Action depuis la modale : envoie un email contenant un LIEN de réinitialisation de profil (nom/prénom/téléphone).
    On ne parle PAS de mot de passe.
    """
    company = get_object_or_404(Company, slug=slug)
    email = (request.POST.get("email") or "").strip().lower()

    # On cherche le parrain existant pour CETTE entreprise
    client = Client.objects.filter(company=company, is_referrer=True, email__iexact=email).first()

    # Toujours message 'succès' pour ne pas divulguer l'existence, mais si on l'a trouvé on envoie réellement.
    if client:
        try:
            link = _build_reset_link(request, client=client)
            subject = f"Réinitialisez votre inscription parrain chez {company.name}"
            body = (
                f"Bonjour {client.first_name or client.last_name or ''},\n\n"
                f"Vous pouvez remettre à jour votre profil parrain (nom, prénom, téléphone) en suivant ce lien :\n"
                f"{link}\n\n"
                f"Ce lien est valable {int(REFERRER_RESET_MAX_AGE/3600)} heures.\n"
                f"— {company.name}"
            )
            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[email],
                fail_silently=False,
            )
        except Exception as e:
            messages.warning(request, f"Le lien de réinitialisation n'a pas pu être envoyé : {e}")

    messages.success(
        request,
        "Si un compte existe pour cet email, un lien de réinitialisation de votre profil vient de vous être envoyé."
    )
    return redirect("public:company_presentation", slug=slug)

def referrer_reset_edit(request, slug: str, token: str):
    """
    Page/traitement via lien signé :
      - Affiche le formulaire pré-rempli (nom, prénom, téléphone) avec email en lecture seule.
      - Met à jour le Client (parrain) de l'entreprise.
    """
    company = get_object_or_404(Company, slug=slug)
    try:
        data = _loads_token(token)
    except signing.SignatureExpired:
        messages.error(request, "Ce lien a expiré. Merci de redemander une réinitialisation.")
        return redirect("public:company_presentation", slug=slug)
    except signing.BadSignature:
        messages.error(request, "Lien invalide.")
        return redirect("public:company_presentation", slug=slug)

    # Vérifications de cohérence
    if data.get("company_id") != company.id:
        messages.error(request, "Lien invalide pour cette entreprise.")
        return redirect("public:company_presentation", slug=slug)

    client = Client.objects.filter(
        pk=data.get("cid"),
        company=company,
        is_referrer=True,
        email__iexact=(data.get("email") or ""),
    ).first()

    if not client:
        messages.error(request, "Impossible de trouver le profil à réinitialiser.")
        return redirect("public:company_presentation", slug=slug)

    if request.method == "POST":
        form = ReferrerResetForm(request.POST, client=client, instance=client)
        if form.is_valid():
            with transaction.atomic():
                form.save()

                # (Optionnel) synchroniser les noms côté User s'il existe
                try:
                    User = get_user_model()
                    u = User.objects.filter(email__iexact=client.email).first()
                    if u:
                        changed = False
                        if u.first_name != client.first_name:
                            u.first_name = client.first_name or ""
                            changed = True
                        if u.last_name != client.last_name:
                            u.last_name = client.last_name or ""
                            changed = True
                        if changed:
                            u.save(update_fields=["first_name", "last_name"])
                except Exception:
                    pass

            messages.success(request, "Votre profil parrain a bien été mis à jour.")
            return redirect("public:company_presentation", slug=slug)
    else:
        form = ReferrerResetForm(client=client, instance=client, initial={
            "last_name": client.last_name,
            "first_name": client.first_name,
            "phone": client.phone,
        })

    # Réutilise le même layout public (tu peux aussi créer un template dédié)
    return render(
        request,
        "public/referrer_reset_edit.html",  # crée un template simple avec {{ form }} et les couleurs de l'entreprise
        {"company": company, "form": form, "client": client},
    )
