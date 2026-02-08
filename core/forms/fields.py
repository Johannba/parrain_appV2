# core/forms/fields.py
from django import forms
from django.core.exceptions import ValidationError
from core.utils.phones import to_e164, ALLOWED_REGIONS_DEFAULT

class InternationalPhoneFormField(forms.CharField):
    def __init__(self, *args, regions=None, **kwargs):
        attrs = kwargs.pop("widget_attrs", {})
        attrs.setdefault("class", "form-control")
        attrs.setdefault(
            "placeholder",
            "Numéro de téléphone",
        )
        kwargs.setdefault("widget", forms.TextInput(attrs=attrs))
        super().__init__(*args, **kwargs)
        self.regions = tuple(regions or ALLOWED_REGIONS_DEFAULT)

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return value
        try:
            return to_e164(value, regions=self.regions)
        except ValueError as e:
            raise ValidationError(str(e))
