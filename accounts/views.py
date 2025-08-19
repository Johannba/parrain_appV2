from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods

from .forms import UserCreateForm, UserUpdateForm, LoginForm
from .models import User, Company
from .permissions import require_superadmin, require_company_admin_or_superadmin
from django.db.models import Q


@require_http_methods(["GET", "POST"])
def logout_view(request):
    logout(request)
    return redirect("accounts:login")


# --- Auth ---
class SignInView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm

class SignOutView(LogoutView):
    next_page = reverse_lazy("accounts:login")

# --- Utilities ---

def qs_users_for(request_user):
    """Restreint le queryset selon le rôle."""
    if request_user.is_superadmin():
        return User.objects.all()
    if request_user.is_admin_entreprise():
        return User.objects.filter(company=request_user.company).exclude(profile="superadmin")
    return User.objects.none()

# --- Users CRUD ---

@method_decorator(login_required, name="dispatch")
class UserListView(ListView):
    template_name = "accounts/users/list.html"
    context_object_name = "users"
    paginate_by = 20

    def get_queryset(self):
        qs = qs_users_for(self.request.user).select_related("company").order_by("username")

        # recherche texte
        q = (self.request.GET.get("q") or "").strip()
        if q:
            qs = qs.filter(
                Q(username__icontains=q) |
                Q(email__icontains=q) |
                Q(first_name__icontains=q) |
                Q(last_name__icontains=q)
            )

        # filtre entreprise (superadmin uniquement)
        company_id = (self.request.GET.get("company") or "").strip()
        if company_id and getattr(self.request.user, "is_superadmin", lambda: False)():
            qs = qs.filter(company_id=company_id)

        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # valeurs courantes des filtres pour garder l’UI en phase
        ctx["current_q"] = (self.request.GET.get("q") or "").strip()
        ctx["current_company"] = (self.request.GET.get("company") or "").strip()
        # liste d’entreprises uniquement pour superadmin → permet d’afficher le <select> dans la topbar
        if getattr(self.request.user, "is_superadmin", lambda: False)():
            ctx["companies_for_filter"] = Company.objects.order_by("name")
        return ctx

    
@method_decorator(login_required, name="dispatch")
class UserCreateView(CreateView):
    template_name = "accounts/users/form.html"
    form_class = UserCreateForm

    def dispatch(self, request, *args, **kwargs):
        require_company_admin_or_superadmin(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request           # <-- pour filtrer le champ company
        return kwargs

    def form_valid(self, form):
        # Un admin ne peut créer que dans SA company (et pas de superadmin)
        if self.request.user.is_admin_entreprise():
            form.instance.company = self.request.user.company   # <-- attribution forcée
            if form.cleaned_data.get("profile") == "superadmin":
                form.add_error("profile", "Création de Superadmin interdite.")
                return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("accounts:user_list")


@method_decorator(login_required, name="dispatch")
class UserUpdateView(UpdateView):
    template_name = "accounts/users/form.html"
    form_class = UserUpdateForm
    model = User

    def dispatch(self, request, *args, **kwargs):
        require_company_admin_or_superadmin(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request           # <-- pour limiter la liste des companies en édition
        return kwargs

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.is_admin_entreprise():
            if obj.company_id != self.request.user.company_id or obj.profile == "superadmin":
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied("Accès refusé.")
        return obj

    def get_success_url(self):
        return reverse("accounts:user_list")

@method_decorator(login_required, name="dispatch")
class UserDeleteView(DeleteView):
    template_name = "accounts/users/confirm_delete.html"
    model = User

    def dispatch(self, request, *args, **kwargs):
        require_company_admin_or_superadmin(request.user)
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if self.request.user.is_admin_entreprise():
            if obj.company_id != self.request.user.company_id or obj.profile == "superadmin":
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied("Accès refusé.")
        return obj

    def get_success_url(self):
        return reverse("accounts:user_list")

# --- Company CRUD (réservé superadmin) ---

@login_required
def company_list(request):
    require_superadmin(request.user)
    companies = Company.objects.all().order_by("name")
    return render(request, "accounts/compagnies/list.html", {"companies": companies})

@login_required
def company_create(request):
    from django.forms import ModelForm, TextInput, CheckboxInput
    require_superadmin(request.user)

    class CompanyForm(ModelForm):
        class Meta:
            model = Company
            fields = ("name", "is_active")
            widgets = {
                "name": TextInput(attrs={"class": "form-control", "placeholder": "Nom"}),
                "is_active": CheckboxInput(attrs={"class": "form-check-input"}),
            }

    if request.method == "POST":
        form = CompanyForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("accounts:company_list")
    else:
        form = CompanyForm()
    return render(request, "accounts/compagnies/form.html", {"form": form})

@login_required
def company_update(request, pk):
    from django.forms import ModelForm
    require_superadmin(request.user)

    class CompanyForm(ModelForm):
        class Meta:
            model = Company
            fields = ("name", "is_active")

    company = get_object_or_404(Company, pk=pk)
    if request.method == "POST":
        form = CompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            return redirect("accounts:company_list")
    else:
        form = CompanyForm(instance=company)
    return render(request, "accounts/compagnies/form.html", {"form": form, "company": company})


@login_required
def company_delete(request, pk):
    require_superadmin(request.user)
    company = get_object_or_404(Company, pk=pk)

    if request.method == "POST":
        company.delete()
        return redirect("accounts:company_list")

    return render(request, "accounts/compagnies/confirm_delete.html", {"company": company})
