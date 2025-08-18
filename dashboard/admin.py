from django.contrib import admin

# Register your models here.
# dashboard/admin.py
from django.contrib import admin
from .models import Client, Referral, Reward

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("last_name", "first_name", "email", "company", "is_referrer")
    search_fields = ("last_name", "first_name", "email", "phone")
    list_filter = ("company", "is_referrer")

@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("referrer", "referee", "company", "status", "created_at")
    list_filter = ("company", "status")
    search_fields = ("referrer__last_name", "referee__last_name")

@admin.register(Reward)
class RewardAdmin(admin.ModelAdmin):
    list_display = ("client", "company", "label", "state", "channel", "code", "created_at")
    list_filter = ("company", "state", "channel")
    search_fields = ("client__last_name", "label", "code")
