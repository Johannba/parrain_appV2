import pytest
from django.urls import reverse

@pytest.mark.django_db
def test_reward_send_sms_requires_login(client):
    url = reverse("rewards:reward_send_sms", kwargs={"pk": 1})
    resp = client.post(url)
    assert resp.status_code in (302, 301)  # redirection vers login
