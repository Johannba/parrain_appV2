import pytest
from accounts.models import Company
from rewards.services.probabilities import ensure_wheel, WheelSpec, draw

pytestmark = pytest.mark.django_db

def test_exact_ratio_80_100(client):
    company = Company.objects.create(name="Test Co")
    spec = WheelSpec(key="ratio_80_100", pairs=((80, "OK"), (20, "KO")))
    ensure_wheel(company, spec)
    hits = [draw(company, "ratio_80_100") for _ in range(100)]
    assert hits.count("OK") == 80
    assert hits.count("KO") == 20
