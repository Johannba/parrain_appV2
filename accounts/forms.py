from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AuthenticationForm
from .models import User, Company



class LoginForm(AuthenticationForm):
    username = forms.CharField(label="Nom d’utilisateur")
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)

class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email", "first_name", "last_name", "profile", "company")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)   # <-- récupère request
        super().__init__(*args, **kwargs)

        if self.request and hasattr(self.request, "user"):
            u = self.request.user
            if u.is_superadmin():
                self.fields["company"].queryset = Company.objects.all()
            elif u.is_admin_entreprise():
                self.fields["company"].queryset = Company.objects.filter(pk=u.company_id)
                self.fields["company"].initial = u.company
                self.fields["company"].widget = forms.HiddenInput()  # <-- cache le champ pour l’admin
            else:
                self.fields["company"].queryset = Company.objects.none()

    def clean(self):
        cleaned = super().clean()
        profile = cleaned.get("profile")
        company = cleaned.get("company")
        if profile in ("admin", "operateur") and not company:
            self.add_error("company", "L’Admin/Opérateur doit être rattaché à une entreprise.")
        if profile == "superadmin" and company:
            self.add_error("company", "Le Superadmin ne doit pas être rattaché à une entreprise.")
        return cleaned


class UserUpdateForm(UserChangeForm):
    password = None
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "profile", "company", "is_active")

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if self.request and hasattr(self.request, "user"):
            u = self.request.user
            if u.is_superadmin():
                self.fields["company"].queryset = Company.objects.all()
            elif u.is_admin_entreprise():
                self.fields["company"].queryset = Company.objects.filter(pk=u.company_id)
            else:
                self.fields["company"].queryset = Company.objects.none()
