# rewards/notifications/services.py
import os
from twilio.rest import Client as TwilioClient

def send_sms(to: str, body: str) -> tuple[bool, str | None]:
    """
    Envoie un SMS via Twilio.
    Retourne (True, None) si OK, sinon (False, "erreur ...").
    """
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    sender = os.getenv("TWILIO_FROM_NUMBER")
    if not (sid and token and sender):
        return False, "Configuration Twilio manquante (env: TWILIO_*)."
    if not to:
        return False, "Numéro du destinataire manquant."

    try:
        client = TwilioClient(sid, token)
        client.messages.create(to=to, from_=sender, body=body)
        return True, None
    except Exception as e:
        return False, str(e)
