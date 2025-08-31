# rewards/forms.py
from django import forms
from .models import RewardTemplate

class RewardTemplateForm(forms.ModelForm):
    cooldown_months = forms.TypedChoiceField(
        choices=[(i, f"{i} mois") for i in range(1, 7)],
        coerce=int,
        label="Délai",
        widget=forms.Select(attrs={"class": "form-select"})
    )

    # NOUVEAU : champ numérique (min = 0)
    min_referrals_required = forms.IntegerField(
        min_value=0,
        label="Minimum de parrainages requis",
        widget=forms.NumberInput(attrs={
            "class": "form-control",
            "placeholder": "0",
            "inputmode": "numeric"
        })
    )

    class Meta:
        model = RewardTemplate
        fields = ("label", "cooldown_months", "min_referrals_required")
        labels = {"label": "Nom de la récompense"}
        widgets = {
            "label": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Ex. -10 %"}
            ),
        }
