from django.shortcuts import render

def mentions_legales(request):
    return render(request, "legal/mentions_legales.html")

def cgu(request):
    return render(request, "legal/cgu.html")

def politique_confidentialite(request):
    return render(request, "legal/politique_confidentialite.html")

def contact(request):
    return render(request, "legal/contact.html")
