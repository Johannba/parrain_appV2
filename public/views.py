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

def _ensure_referrer_user(*, email: str, company: Company, first_name: str = "", last_name: str = ""):
    """
    Assure qu'un accounts.User existe pour cet email :
      - username = email
      - profile = CLIENT (rôle neutre = “aucun rôle”)
      - company = l’entreprise courante
      - mot de passe utilisable aléatoire si absent/inutilisable
    Retourne (user, created: bool)
    """
    User = get_user_model()
    email = (email or "").strip()
    if not email:
        return None, False

    u = User.objects.filter(email__iexact=email).first()
    if u:
        changed = False
        # mot de passe utilisable (si jamais on avait un unusable)
        if not u.has_usable_password():
            u.set_password(get_random_string(32)); changed = True
        # compléter les champs vides utiles
        if first_name and not u.first_name:
            u.first_name = first_name; changed = True
        if last_name and not u.last_name:
            u.last_name = last_name; changed = True
        # rôle neutre + rattachement
        if hasattr(u, "profile") and u.profile != User.Profile.CLIENT:
            u.profile = User.Profile.CLIENT; changed = True
        if hasattr(u, "company") and company and not u.company_id:
            u.company = company; changed = True
        if not u.is_active:
            u.is_active = True; changed = True
        if changed:
            u.save()
        return u, False

    # création
    u = User(
        username=email,           # AbstractUser -> username requis
        email=email,
        first_name=first_name or "",
        last_name=last_name or "",
        is_active=True,
    )
    if hasattr(u, "profile"):
        u.profile = User.Profile.CLIENT
    if hasattr(u, "company") and company:
        u.company = company
    u.set_password(get_random_string(32))
    u.save()
    return u, True


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
    """Garantit un accounts.User avec mot de passe utilisable et profil 'CLIENT'."""
    User = get_user_model()
    email = (email or "").strip()
    if not email:
        return None, False

    u = User.objects.filter(email__iexact=email).first()
    if u:
        changed = False
        if not u.has_usable_password():
            u.set_password(get_random_string(32)); changed = True
        if first_name and not u.first_name:
            u.first_name = first_name; changed = True
        if last_name and not u.last_name:
            u.last_name = last_name; changed = True
        if hasattr(u, "profile") and u.profile != User.Profile.CLIENT:
            u.profile = User.Profile.CLIENT; changed = True
        if hasattr(u, "company") and company and not u.company_id:
            u.company = company; changed = True
        if not u.is_active:
            u.is_active = True; changed = True
        if changed:
            u.save()
        return u, False

    u = User(
        username=email,
        email=email,
        first_name=first_name or "",
        last_name=last_name or "",
        is_active=True,
    )
    if hasattr(u, "profile"):
        u.profile = User.Profile.CLIENT
    if hasattr(u, "company") and company:
        u.company = company
    u.set_password(get_random_string(32))
    u.save()
    return u, True


def _send_password_reset(request, email: str) -> bool:
    """Envoie l'email de réinitialisation si un User existe (comportement standard)."""
    if not email:
        return False
    frm = PasswordResetForm(data={"email": email})
    if not frm.is_valid():
        return False
    frm.save(
        request=request,
        use_https=request.is_secure(),
   
        subject_template_name="registration/password_reset_subject.txt",
        email_template_name="registration/password_reset_email.txt",
        html_email_template_name="registration/password_reset_email.html",
        from_email=settings.DEFAULT_FROM_EMAIL
    )
    return True


def referrer_register(request, slug: str):
    """
    Inscription d'un parrain depuis la page publique de présentation d'une entreprise.

    Règles métier :
      - Si l'e-mail correspond déjà à un parrain de cette entreprise -> ne recrée pas, mais envoie un e-mail de (ré)initialisation.
      - Si l'inscription est nouvelle -> crée le Client (parrain), puis crée/assure un accounts.User et envoie l'e-mail de (ré)initialisation.
      - Si le formulaire est invalide mais qu'un e-mail est fourni -> tente quand même d'assurer le compte user et d'envoyer l'e-mail.
      - En cas de race condition (IntegrityError) -> traite comme "déjà inscrit" et envoie l'e-mail.

    UX :
      - Succès (création) : message succès + info d'envoi e-mail -> redirect.
      - Déjà inscrit / invalide avec email : message info + redirect (ou render si on veut ré-afficher les erreurs).
    """
    company = get_object_or_404(Company, slug=slug)

    # GET → on renvoie vers la page de présentation (pas d'inscription en GET)
    if request.method != "POST":
        return redirect("public:company_presentation", slug=slug)

    form = ReferrerForm(request.POST, company=company)

    # Champs utiles (normalisés tôt)
    posted_email = (request.POST.get("email") or "").strip()
    posted_fn = (request.POST.get("first_name") or "").strip()
    posted_ln = (request.POST.get("last_name") or "").strip()

    if form.is_valid():
        # Est-ce déjà un parrain par e-mail ?
        already_by_email = bool(
            posted_email
            and Client.objects.filter(
                company=company, email__iexact=posted_email, is_referrer=True
            ).exists()
        )

        if not already_by_email:
            # Tentative de création du parrain
            ref = form.save(commit=False)
            ref.company = company
            ref.is_referrer = True

            try:
                with transaction.atomic():
                    ref.save()
            except IntegrityError:
                # Cas de concurrence/doublon : on bascule sur le flux "déjà inscrit"
                if posted_email:
                    _ensure_referrer_user(
                        email=posted_email, company=company,
                        first_name=posted_fn, last_name=posted_ln
                    )
                    _send_password_reset(request, posted_email)
                    messages.info(
                        request,
                        "Tu es déjà inscrit comme parrain. "
                        "Un e-mail de (ré)initialisation vient d’être envoyé s’il existe un compte."
                    )
                # On peut choisir de ré-afficher la page avec erreurs, mais le plus simple ici :
                return redirect("public:company_presentation", slug=slug)

            # Création OK → on assure le compte user puis on envoie le reset
            if posted_email:
                _ensure_referrer_user(
                    email=posted_email, company=company,
                    first_name=posted_fn, last_name=posted_ln
                )
                _send_password_reset(request, posted_email)

            messages.success(
                request,
                "Inscription confirmée. "
                "Un e-mail vient de t’être envoyé pour définir ton mot de passe."
            )
            return redirect("public:company_presentation", slug=slug)

        # already_by_email == True → on n’essaie pas de recréer, on envoie juste l’e-mail
        if posted_email:
            _ensure_referrer_user(
                email=posted_email, company=company,
                first_name=posted_fn, last_name=posted_ln
            )
            _send_password_reset(request, posted_email)

        messages.info(
            request,
            "Tu es déjà inscrit comme parrain. "
            "Un e-mail de (ré)initialisation vient d’être envoyé s’il existe un compte."
        )
        return redirect("public:company_presentation", slug=slug)

    # Formulaire invalide : si un e-mail a été fourni, on déclenche quand même le reset
    if posted_email:
        _ensure_referrer_user(
            email=posted_email, company=company,
            first_name=posted_fn, last_name=posted_ln
        )
        _send_password_reset(request, posted_email)
        messages.info(
            request,
            "Tu es déjà inscrit comme parrain (ou des informations sont invalides). "
            "Un e-mail de (ré)initialisation vient d’être envoyé s’il existe un compte."
        )

    # On ré-affiche la page avec les erreurs du formulaire
    return render(
        request,
        "public/company_presentation.html",
        {"company": company, "form": form, "form_errors": True},
    )

def root_view(request):
    if request.user.is_authenticated:
        return redirect("/dashboard/")  # ou une autre page interne
    return render(request, "public/home.html")
