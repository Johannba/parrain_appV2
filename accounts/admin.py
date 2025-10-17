from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from .models import User, Company

@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    search_fields = ("name", "slug")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}

@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ("Informations personnelles", {'fields': ('first_name', 'last_name', 'email')}),
        ("Rôle & Entreprise", {'fields': ('profile', 'company')}),
        ("Permissions", {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ("Dates importantes", {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('username', 'password1', 'password2', 'profile', 'company')}),
    )

    # 🔒 Empêche l’édition manuelle de la date
    readonly_fields = ('last_login', 'date_joined')

    # 👀 Colonne “Créé le” dans la liste + filtres & navigation par date
    list_display = ('username', 'email', 'profile', 'company', 'is_active', 'is_staff', 'created_at')
    list_filter  = ('profile', 'company', 'is_active', 'is_staff', 'date_joined')
    date_hierarchy = 'date_joined'
    ordering = ('username',)

    @admin.display(description="Créé le", ordering='date_joined')
    def created_at(self, obj):
        return obj.date_joined  # ou formatté si tu préfères
        # from django.utils.timezone import localtime
        # from django.utils.formats import date_format
        # return date_format(localtime(obj.date_joined), "SHORT_DATETIME_FORMAT")