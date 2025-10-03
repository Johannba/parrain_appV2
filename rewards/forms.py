# rewards/forms.py
from django import forms
from .models import RewardTemplate

class RewardTemplateForm(forms.ModelForm):
    # Limite à 17 caractères (serveur) + maxlength côté HTML
    label = forms.CharField(
        max_length=17,
        label="Nom de la récompense",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Ex. -10 %",
            "maxlength": "17",   # limite côté navigateur
        }),
        error_messages={
            "max_length": "Maximum 17 caractères.",
        },
    )

    cooldown_months = forms.TypedChoiceField(
        choices=[(i, f"{i} mois") for i in range(1, 7)],
        coerce=int,
        label="Délai",
        widget=forms.Select(attrs={"class": "form-select"})
    )

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

    def clean_label(self):
        """Validation supplémentaire (au cas où, après trim)."""
        value = (self.cleaned_data.get("label") or "").strip()
        if len(value) > 17:
            raise forms.ValidationError("Maximum 17 caractères.")
        return value
