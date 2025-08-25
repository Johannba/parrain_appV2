from django import forms
from .models import RewardTemplate

class RewardTemplateForm(forms.ModelForm):
    # TypedChoiceField so we store an integer, not a string
    cooldown_months = forms.TypedChoiceField(
        choices=[(i, f"{i} mois") for i in range(1, 7)],
        coerce=int,
        label="Délai",
        widget=forms.Select(attrs={"class": "form-select"})  # <-- Bootstrap styling here
    )

    class Meta:
        model = RewardTemplate
        fields = ("label", "cooldown_months")
        labels = {"label": "Nom de la récompense"}
        widgets = {
            "label": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex. -10 %"}
            ),
        }

