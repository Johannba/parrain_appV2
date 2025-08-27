# rewards/admin.py
from django.contrib import admin, messages
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from .models import ProbabilityWheel, RewardTemplate, Reward
# Services pour piloter les roues depuis l’admin
from .services.probabilities import (
    BASE_KEY, VERY_RARE_KEY,
    ensure_wheels, rebuild_wheel, reset_wheel
)


# ============ Actions utilitaires ============

@admin.action(description="Marquer sélection comme Envoyée")
def mark_sent(modeladmin, request, queryset):
    updated = queryset.update(state="SENT")
    messages.success(request, _(f"{updated} récompense(s) marquée(s) comme envoyée(s)."))

@admin.action(description="Marquer sélection comme En attente")
def mark_pending(modeladmin, request, queryset):
    updated = queryset.update(state="PENDING")
    messages.success(request, _(f"{updated} récompense(s) marquée(s) comme en attente."))

@admin.action(description="Marquer sélection comme Désactivée")
def mark_disabled(modeladmin, request, queryset):
    updated = queryset.update(state="DISABLED")
    messages.success(request, _(f"{updated} récompense(s) désactivée(s)."))

@admin.action(description="Archiver la sélection")
def mark_archived(modeladmin, request, queryset):
    updated = queryset.update(state="ARCHIVED")
    messages.success(request, _(f"{updated} récompense(s) archivée(s)."))


# ============ Reward ============

@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    """
    Gestion des récompenses instanciées (par client).
    - Recherche par client / email / libellé
    - Filtres par entreprise / type / état / date
    - Actions de changement d’état
    """
    list_display = (
        "company", "client", "referral",
        "label", "bucket", "state", "created_at",
    )
    list_filter = (
        "company", "bucket", "state", ("created_at", admin.DateFieldListFilter),
    )
    search_fields = (
        "label",
        "client__last_name", "client__first_name",
        "client__email", "client__phone",
    )
    list_select_related = ("company", "client", "referral")
    autocomplete_fields = ("client", "referral")
    raw_id_fields = ()
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-id")
    actions = [mark_sent, mark_pending, mark_disabled, mark_archived]

    # Optionnel: protéger la contrainte unique (company, client, referral) côté admin
    def save_model(self, request, obj, form, change):
        try:
            with transaction.atomic():
                super().save_model(request, obj, form, change)
        except IntegrityError:
            self.message_user(
                request,
                _("Une récompense existe déjà pour ce parrainage et ce parrain (règle: 1 par filleul)."),
                level=messages.ERROR,
            )


# ============ RewardTemplate ============

@admin.register(RewardTemplate)
class RewardTemplateAdmin(admin.ModelAdmin):
    """
    Les 4 templates fixes par entreprise.
    - Seuls label + cooldown_months sont modifiables.
    - Affiche cooldown_days et probability_display en lecture seule.
    """
    list_display = (
        "company", "bucket", "label",
        "cooldown_months", "cooldown_days", "probability_display",
    )
    list_filter = ("company", "bucket")
    search_fields = ("label", "company__name")
    ordering = ("company", "bucket")
    readonly_fields = ("cooldown_days", "probability_display")


# ============ ProbabilityWheel ============

@admin.action(description="(Re)créer les deux roues pour l’entreprise (ensure_wheels)")
def action_ensure_wheels(modeladmin, request, queryset):
    """
    Pour chaque roue sélectionnée, on régénère (idempotent) les DEUX roues
    de l’entreprise afin d’assurer les tailles exactes (base et very_rare).
    """
    companies = {w.company for w in queryset}
    for c in companies:
        ensure_wheels(c)
    messages.success(request, _(f"Roues vérifiées/régénérées pour {len(companies)} entreprise(s)."))

@admin.action(description="Régénérer la roue sélectionnée (repart à idx=0)")
def action_rebuild_selected(modeladmin, request, queryset):
    for w in queryset:
        key = w.key
        try:
            rebuild_wheel(w.company, key)
        except ValueError:
            messages.error(request, _(f"Clé inconnue pour {w}: {key}"))
    messages.success(request, _("Roue(s) régénérée(s)."))

@admin.action(description="Remettre le curseur (idx) à 0")
def action_reset_idx(modeladmin, request, queryset):
    for w in queryset:
        reset_wheel(w.company, w.key)
    messages.success(request, _("Curseur réinitialisé à 0 pour la sélection."))


@admin.register(ProbabilityWheel)
class ProbabilityWheelAdmin(admin.ModelAdmin):
    """
    Visualisation et maintenance des roues.
    """
    list_display = ("company", "key", "size", "idx")
    list_filter = ("company", "key")
    search_fields = ("company__name", "key")
    readonly_fields = ("size", "idx")
    actions = [action_ensure_wheels, action_rebuild_selected, action_reset_idx]
