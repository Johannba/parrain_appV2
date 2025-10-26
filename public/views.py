# public/views.py
from __future__ import annotations

from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db import IntegrityError, transaction

from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string

from accounts.models import Company
from dashboard.models import Client
from .forms import ReferrerForm
from rewards.models import RewardTemplate
from django.contrib.auth.forms import PasswordResetForm
from django.conf import settings


# ---------------------------
# Helpers
# ---------------------------

# def _ensure_referrer_user(*, email: str, company: Company, first_name: str = "", last_name: str = ""):
#     """
#     Assure qu'un accounts.User existe pour cet email :
#       - username = email
#       - profile = CLIENT (rôle neutre = “aucun rôle”)
#       - company = l’entreprise courante
#       - mot de passe utilisable aléatoire si absent/inutilisable
#     Retourne (user, created: bool)
#     """
#     User = get_user_model()
#     email = (email or "").strip()
#     if not email:
#         return None, False

#     u = User.objects.filter(email__iexact=email).first()
#     if u:
#         changed = False
#         # mot de passe utilisable (si jamais on avait un unusable)
#         if not u.has_usable_password():
#             u.set_password(get_random_string(32)); changed = True
#         # compléter les champs vides utiles
#         if first_name and not u.first_name:
#             u.first_name = first_name; changed = True
#         if last_name and not u.last_name:
#             u.last_name = last_name; changed = True
#         # rôle neutre + rattachement
#         if hasattr(u, "profile") and u.profile != User.Profile.CLIENT:
#             u.profile = User.Profile.CLIENT; changed = True
#         if hasattr(u, "company") and company and not u.company_id:
#             u.company = company; changed = True
#         if not u.is_active:
#             u.is_active = True; changed = True
#         if changed:
#             u.save()
#         return u, False

#     # création
#     u = User(
#         username=email,           # AbstractUser -> username requis
#         email=email,
#         first_name=first_name or "",
#         last_name=last_name or "",
#         is_active=True,
#     )
#     if hasattr(u, "profile"):
#         u.profile = User.Profile.CLIENT
#     if hasattr(u, "company") and company:
#         u.company = company
#     u.set_password(get_random_string(32))
#     u.save()
#     return u, True


# ---------------------------
# Vues publiques
# ---------------------------

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

    # 8 cases en répétant l’ordre (S, M, R, TR, S, M, R, TR)
    wheel_labels = (base_labels * ((8 + len(base_labels) - 1) // len(base_labels)))[:8]

    return render(request, "public/company_presentation.html", {
        "company": company,
        "form": form,
        "wheel_labels": wheel_labels,
    })

# public/views.py (extrait)
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth import get_user_model
from django.utils.crypto import get_random_string

from accounts.models import Company
from dashboard.models import Client
from .forms import ReferrerForm

def _ensure_referrer_user(*, email, company, first_name="", last_name=""):
    """
    Ne crée rien.
    Si un User avec cet email existe :
      - assure un mot de passe utilisable (si absent)
      - complète first_name / last_name s’ils sont vides
      - force le profil CLIENT (si l’attribut 'profile' existe)
      - rattache la company si absente (si l’attribut 'company' existe)
      - réactive le compte si inactif
    Retourne (user|None, created=False)
    """
    User = get_user_model()
    email = (email or "").strip()
    if not email:
        return None, False

    u = User.objects.filter(email__iexact=email).first()
    if not u:
        # NE PAS créer d’utilisateur
        return None, False

    changed = False

    # Mot de passe utilisable
    if not u.has_usable_password():
        u.set_password(get_random_string(32))
        changed = True

    # Compléter les champs vides
    if first_name and not u.first_name:
        u.first_name = first_name
        changed = True
    if last_name and not u.last_name:
        u.last_name = last_name
        changed = True

    # Rôle neutre CLIENT (si l’attribut existe)
    if hasattr(u, "profile"):
        try:
            if u.profile != User.Profile.CLIENT:
                u.profile = User.Profile.CLIENT
                changed = True
        except Exception:
            # Si votre modèle n’a pas User.Profile.CLIENT, on ignore
            pass

    # Rattacher la company si non renseignée (si l’attribut existe)
    if hasattr(u, "company") and company and not getattr(u, "company_id", None):
        u.company = company
        changed = True

    # Réactiver si nécessaire
    if not u.is_active:
        u.is_active = True
        changed = True

    if changed:
        u.save()

    return u, False



def _send_password_reset(request, email: str) -> bool:
    if not email:
        return False
    frm = PasswordResetForm(data={"email": email})
    if not frm.is_valid():
        return False
    frm.save(
        request=request,
        use_https=request.is_secure(),
        subject_template_name="accounts/emails/password_reset_subject.txt",
        email_template_name="accounts/emails/password_reset_email.txt",
        html_email_template_name="accounts/emails/password_reset_email.html",
        from_email=settings.DEFAULT_FROM_EMAIL,
    )
    return True



def referrer_register(request, slug: str):
    """
    Inscription d'un parrain depuis la page publique.
    - Affiche UNIQUEMENT des erreurs (email/phone déjà utilisés, form invalide).
    - En cas de succès: création silencieuse + envoi reset password possible, puis redirect sans messages.
    - Si l'email existe déjà comme parrain dans l'entreprise : on déclenche une modale
      proposant l'envoi d'un lien de "réinitialisation" (mot de passe oublié).
    """
    company = get_object_or_404(Company, slug=slug)

    # helper local pour les libellés de la roue (nécessaires au template lors d'un render avec erreurs)
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
        # Email déjà parrain pour cette entreprise → erreur sur le champ email + déclenchement du pop-up
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
                    # 👇 Flags pour déclencher le pop-up de réinitialisation
                    "suggest_reset": True,
                    "suggest_reset_email": posted_email,
                    "suggest_reset_first_name": posted_fn,
                    "suggest_reset_last_name": posted_ln,
                },
            )

        # Création du parrain
        ref = form.save(commit=False)
        ref.company = company
        ref.is_referrer = True
        try:
            with transaction.atomic():
                ref.save()
        except IntegrityError as e:
            # Doublons DB (unique phone/email, etc.) → map vers champs si possible
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

        # Succès silencieux : on assure le compte et on envoie le reset SANS message
        if posted_email:
            _ensure_referrer_user(
                email=posted_email, company=company,
                first_name=posted_fn, last_name=posted_ln
            )
            _send_password_reset(request, posted_email)

        # Redirection propre, aucun message à afficher
        return redirect("public:company_presentation", slug=slug)

    # Form invalide → réaffiche avec erreurs (aucun email envoyé ici)
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

from django.views.decorators.http import require_POST

@require_POST
def referrer_reset_access(request, slug: str):
    """
    Depuis le pop-up : envoie un email de réinitialisation au parrain détecté.
    Ne révèle pas si le compte existe (anti user-enumeration).
    """
    company = get_object_or_404(Company, slug=slug)
    email = (request.POST.get("email") or "").strip()

    # Rendre le compte "réinitialisable" s'il existe (sans créer)
    _ensure_referrer_user(
        email=email, company=company,
        first_name=request.POST.get("first_name", "").strip(),
        last_name=request.POST.get("last_name", "").strip(),
    )

    # Envoi du mail de reset (si le formulaire Django l'accepte)
    _send_password_reset(request, email)

    messages.success(
        request,
        "Si un compte existe pour cet email, un lien de réinitialisation vient de vous être envoyé."
    )
    return redirect("public:company_presentation", slug=slug)
