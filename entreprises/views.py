from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, get_object_or_404
from accounts.permissions import require_company_admin_or_superadmin

# Si tu as un modèle Client plus tard, on branchera ici.
# Pour le moment on renvoie le template tel quel (design statique).

@login_required
def clients_list(request):
    u = request.user
    # Superadmin toujours OK, sinon Admin/Opérateur requis
    try:
        require_company_admin_or_superadmin(u)
    except PermissionDenied:
        # Autoriser explicitement l'opérateur
        if not (hasattr(u, "is_operateur") and u.is_operateur()):
            raise

    # Plus tard: filtrer les clients de u.company
    context = {}
    return render(request, "entreprises/clients_list.html", context)

@login_required
def client_detail(request, pk):
    u = request.user
    try:
        require_company_admin_or_superadmin(u)
    except PermissionDenied:
        if not (hasattr(u, "is_operateur") and u.is_operateur()):
            raise

    # Placeholder: quand tu auras un modèle, récupère le client de l’entreprise
    # client = get_object_or_404(Client, pk=pk, company=u.company)  # exemple
    context = {}  # {"client": client}
    return render(request, "entreprises/client_detail.html", context)
