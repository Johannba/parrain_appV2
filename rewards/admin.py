from django.contrib import admin
from rewards.models import ProbabilityWheel

@admin.register(ProbabilityWheel)
class ProbabilityWheelAdmin(admin.ModelAdmin):
    list_display = ("company", "key", "size", "idx")
    list_filter = ("company", "key")
    search_fields = ("company__name", "key")
    readonly_fields = ("size", "idx")
