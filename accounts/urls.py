from django.urls import path
from .views import (
    SignInView, logout_view,
    UserListView, UserCreateView, UserUpdateView, UserDeleteView,
    company_list, company_create, company_update,company_delete 
)
from . import views

app_name = "accounts"

urlpatterns = [
    # Auth
    path("login/", SignInView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),

    # Users CRUD
    path("users/", UserListView.as_view(), name="user_list"),
    path("users/create/", UserCreateView.as_view(), name="user_create"),
    path("users/<int:pk>/edit/", UserUpdateView.as_view(), name="user_edit"),
    path("users/<int:pk>/delete/", UserDeleteView.as_view(), name="user_delete"),

    # Companies (superadmin only)
    path("companies/", company_list, name="company_list"),
    path("companies/create/", company_create, name="company_create"),
    path("companies/<int:pk>/edit/", views.company_update, name="company_update"),
    path("companies/<int:pk>/delete/", views.company_delete, name="company_delete"),

]
