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
    form = ReferrerForm(company=company)

    # Récupère les 4 templates (ordre souhaité)
    order = ["SOUVENT", "MOYEN", "RARE", "TRES_RARE"]
    tpls = {t.bucket: t for t in RewardTemplate.objects.filter(company=company)}

    base_labels = []
    for b in order:
        lbl = (tpls.get(b).label or "").strip() if tpls.get(b) else ""
        base_labels.append(lbl or b.title())

    # 8 cases
    wheel_labels = (base_labels * ((8 + len(base_labels) - 1) // len(base_labels)))[:8]

    return render(request, "public/company_presentation.html", {
        "company": company,
        "form": form,
        "wheel_labels": wheel_labels,
    })

def referrer_register(request, slug: str):
    """
    Inscription d'un parrain depuis la page publique.
    - Si l'email est déjà utilisé par un parrain de l'entreprise :
      on déclenche une modale proposant d'envoyer un LIEN DE RÉINITIALISATION DE PROFIL (pas mot de passe).
    - Sinon : on crée le parrain et on redirige proprement.
    """
    company = get_object_or_404(Company, slug=slug)

    def _wheel_labels_for(_company: Company):
        order = ["SOUVENT", "MOYEN", "RARE", "TRES_RARE"]
        tpls = {t.bucket: t for t in RewardTemplate.objects.filter(company=_company)}
        base = []
        for b in order:
            lbl = (tpls.get(b).label or "").strip() if tpls.get(b) else ""
            base.append(lbl or b.title())
        return (base * ((8 + len(base) - 1) // len(base)))[:8]

    if request.method != "POST":
        return redirect("public:company_presentation", slug=slug)

    form = ReferrerForm(request.POST, company=company)

    posted_email = (request.POST.get("email") or "").strip()
    posted_fn = (request.POST.get("first_name") or "").strip()
    posted_ln = (request.POST.get("last_name") or "").strip()

    if form.is_valid():
        # 1) Email déjà parrain pour cette entreprise ? -> erreur + ouverture du pop-up "réinit profil"
        already_by_email = bool(
            posted_email and Client.objects.filter(
                company=company, email__iexact=posted_email, is_referrer=True
            ).exists()
        )
        if already_by_email:
            form.add_error("email", "Cet email est déjà utilisé par un parrain de cette entreprise.")
            return render(
                request,
                "public/company_presentation.html",
                {
                    "company": company,
                    "form": form,
                    "wheel_labels": _wheel_labels_for(company),
                    "form_errors": True,
                    # Flags -> modale qui propose l'envoi du lien de RÉINITIALISATION DE PROFIL
                    "suggest_reset": True,
                    "suggest_reset_email": posted_email,
                    "suggest_reset_first_name": posted_fn,
                    "suggest_reset_last_name": posted_ln,
                },
            )

        # 2) Création du parrain
        ref = form.save(commit=False)
        ref.company = company
        ref.is_referrer = True
        try:
            with transaction.atomic():
                ref.save()
        except IntegrityError as e:
            emsg = str(e).lower()
            if "phone" in emsg or "téléphone" in emsg or "telephone" in emsg:
                form.add_error("phone", "Ce numéro de téléphone est déjà utilisé.")
            elif "email" in emsg:
                form.add_error("email", "Cet email est déjà utilisé.")
            else:
                form.add_error(None, "Ce parrain existe déjà pour cette entreprise.")
            return render(
                request,
                "public/company_presentation.html",
                {
                    "company": company,
                    "form": form,
                    "wheel_labels": _wheel_labels_for(company),
                    "form_errors": True,
                },
            )

        # 3) Succès silencieux → redirect
        return redirect("public:company_presentation", slug=slug)

    # Form invalide → réaffiche avec erreurs
    return render(
        request,
        "public/company_presentation.html",
        {
            "company": company,
            "form": form,
            "wheel_labels": _wheel_labels_for(company),
            "form_errors": True,
        },
    )

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
