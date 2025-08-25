from django.contrib import admin

# Register your models here.
# dashboard/admin.py
from django.contrib import admin
from .models import Client, Referral

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email", "company", "is_referrer")
    search_fields = ("last_name", "first_name", "email", "phone")
    list_filter = ("company", "is_referrer")

@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display  = ("id", "company", "referrer", "referee", "created_at")
    list_filter   = ("company",)                # ← plus de "status" ici
    search_fields = ("referrer__last_name", "referrer__first_name",
                     "referee__last_name", "referee__first_name")
    autocomplete_fields = ("company", "referrer", "referee")
    date_hierarchy = "created_at"

