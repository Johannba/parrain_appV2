from django.shortcuts import render

def cgu_view(request):
    template = (
        "legal/cgu.html"
        if request.user.is_authenticated
        else "legal_public/cgu.html"
    )
    return render(request, template)

def mentions_view(request):
    template = (
        "legal/mentions_legales.html"
        if request.user.is_authenticated
        else "legal_public/mentions_legales.html"
    )
    return render(request, template)

def privacy_view(request):
    template = (
        "legal/politique_confidentialite.html"
        if request.user.is_authenticated
        else "legal_public/politique_confidentialite.html"
    )
    return render(request, template)

def contact_view(request):
    template = (
        "legal/contact.html"
        if request.user.is_authenticated
        else "legal_public/contact.html"
    )
    return render(request, template)
