# rewards/forms.py
from django import forms
from dashboard.models import Reward

class RewardForm(forms.ModelForm):
    # Libellés clairs pour la catégorie probabilité
    CATEGORIE_PROBABILITE_CHOICES = [
        ("SOUVENT", "Souvent (~80/100)"),
        ("MOYEN", "Moyen (~20/100)"),
        ("RARE", "Rare (~1/100)"),
        ("TRES_RARE", "Très rare (~1/10000)"),
    ]

    bucket = forms.ChoiceField(
        label="Catégorie probabilité",
        choices=CATEGORIE_PROBABILITE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # Nouveau champ d'UI: 1..6 mois -> mappé vers cooldown_days
    cooldown_months = forms.ChoiceField(
        label="Délai",
        choices=[(str(m), f"{m} mois") for m in range(1, 7)],
        widget=forms.Select(attrs={"class": "form-select"}),
        required=False,
    )

    class Meta:
        model = Reward
        # On expose uniquement les champs utiles à la création/édition
        fields = [
            "label",
            "code",
            "bucket",
            "min_obtention",   # renommé visuellement ci-dessous
            "cooldown_days",   # caché et piloté par cooldown_months
        ]
        widgets = {
            "label": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex. -10% de remise"}),
            "code": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex. CODE10"}),
            "min_obtention": forms.NumberInput(attrs={"class": "form-control", "min": 0}),
            "cooldown_days": forms.HiddenInput(),  # on le calcule depuis cooldown_months
        }
        labels = {
            "min_obtention": "Minimum parrainage requis",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Si tu conserves state/channel/weight dans le modèle, ils ne sont pas exposés ici.
        # Préremplir cooldown_months si l'instance a déjà un cooldown_days
        inst = getattr(self, "instance", None)
        if inst and getattr(inst, "pk", None):
            days = inst.cooldown_days or 0
            # Conversion simple sur base 30 jours
            months = (days // 30) if days else None
            if months and 1 <= months <= 6:
                self.fields["cooldown_months"].initial = str(months)

    def clean(self):
        cleaned = super().clean()
        # Mapper cooldown_months -> cooldown_days (30 jours / mois)
        months_str = cleaned.get("cooldown_months")
        if months_str:
            try:
                months = int(months_str)
                months = min(max(months, 1), 6)  # borne 1..6
                cleaned["cooldown_days"] = months * 30
            except (TypeError, ValueError):
                cleaned["cooldown_days"] = 0
        else:
            cleaned["cooldown_days"] = 0
        return cleaned
