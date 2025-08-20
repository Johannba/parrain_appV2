from django import forms
from dashboard.models import Reward  

class RewardForm(forms.ModelForm):
    class Meta:
        model = Reward
        fields = ("label", "code", "channel", "state", "client")
        widgets = {
            "label":  forms.TextInput(attrs={"class": "form-control"}),
            "code":   forms.TextInput(attrs={"class": "form-control"}),
            "channel":forms.TextInput(attrs={"class": "form-control"}),
            "state":  forms.Select(attrs={"class": "form-select"}),
            "client": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        # Filtrer les clients par entreprise pour un admin d’entreprise
        u = getattr(request, "user", None)
        if hasattr(u, "is_admin_entreprise") and u.is_admin_entreprise():
            self.fields["client"].queryset = self.fields["client"].queryset.filter(company=u.company)
