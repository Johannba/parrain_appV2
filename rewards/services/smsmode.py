# rewards/services/smsmode.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import json
import logging
import requests
from django.conf import settings
from common.phone_utils import normalize_msisdn  # ← version canonique (retourne (e164, meta))

logger = logging.getLogger(__name__)

__all__ = [
    "SMSPayload",
    "SMSResult",
    "build_reward_sms_text",
    "_build_smsmode_url",
    "send_sms",
    "normalize_msisdn",  # on réexporte pour les appels existants
]

# =========================
# Modèles de données
# =========================

@dataclass
class SMSPayload:
    to: str
    text: str
    sender: Optional[str] = None

@dataclass
class SMSResult:
    ok: bool
    provider_id: Optional[str]
    status: str
    raw: Dict[str, Any]

# =========================
# Message métier
# =========================

def build_reward_sms_text(*, client_fullname: str, claim_absolute_url: str, company_name: str | None) -> str:
    parts = []
    parts.append(f"{company_name}:" if company_name else "Votre récompense :")
    parts.append(
        f"{client_fullname}, vous avez une récompense en attente."
        if client_fullname else
        "Vous avez une récompense en attente."
    )
    parts.append(f"Utilisez-la ici : {claim_absolute_url}")
    return " ".join(parts)

# =========================
# Construction d'URL smsmode
# =========================

def _build_smsmode_url() -> str:
    """
    Construit l'URL finale sans double 'sms/v1'.
    - Si BASE_URL se termine déjà par '/sms/v1' => ajoute '/messages'
    - Sinon => ajoute '/sms/v1/messages'
    """
    base = settings.SMSMODE["BASE_URL"].rstrip("/")  # ex: https://rest.smsmode.com
    if base.endswith("/sms/v1"):
        return f"{base}/messages"
    return f"{base}/sms/v1/messages"

# =========================
# Envoi
# =========================

def send_sms(payload: SMSPayload) -> SMSResult:
    """
    Envoi via smsmode.
    Auth: header 'X-Api-Key: <API_KEY>'
    Endpoint attendu: https://rest.smsmode.com/sms/v1/messages

    Corps JSON (conforme smsmode):
      {
        "recipient": {"to": "+33XXXXXXXXX"},
        "body": {"text": "message"},
        "from": "ParrainApp"  # optionnel selon contrat
      }
    """
    if settings.SMSMODE.get("DRY_RUN"):
        logger.info("[SMSMODE DRY-RUN] %s", payload)
        return SMSResult(ok=True, provider_id=None, status="DRY_RUN", raw={"dry_run": True})

    url = _build_smsmode_url()

    headers = {
        "X-Api-Key": settings.SMSMODE["API_KEY"],   # ✅ auth correcte
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Normalisation stricte en E.164 (fallback sur la valeur brute si besoin)
    to_e164, meta = normalize_msisdn(
        payload.to,
        default_region=getattr(settings, "SMS_DEFAULT_REGION", "FR"),
    )
    final_to = (meta.get("e164") or to_e164 or payload.to)
    if final_to != payload.to:
        logger.info("SMSMODE normalize: raw=%s -> e164=%s", payload.to, final_to)

    data: Dict[str, Any] = {
        "recipient": {"to": final_to},   # ← toujours E.164 si possible
        "body": {"text": payload.text},  # ← champ attendu
    }
    if payload.sender:
        data["from"] = payload.sender    # optionnel selon contrat

    logger.info("SMSMODE POST %s to=%s sender=%s", url, final_to, payload.sender or "")

    try:
        resp = requests.post(url, headers=headers, data=json.dumps(data), timeout=settings.SMSMODE["TIMEOUT"])
        ctype = (resp.headers.get("Content-Type") or "").lower()
        raw: Dict[str, Any] = resp.json() if "application/json" in ctype else {"text": resp.text}
        ok = 200 <= resp.status_code < 300

        # id de message (peut être messageId ou messageIds[])
        provider_id: Optional[str] = None
        if isinstance(raw.get("messageIds"), list) and raw["messageIds"]:
            provider_id = raw["messageIds"][0]
        else:
            provider_id = raw.get("messageId")

        status = raw.get("status") or ("OK" if ok else f"HTTP_{resp.status_code}")
        if not ok:
            logger.error("SMSMODE error: %s (status=%s url=%s)", raw, resp.status_code, url)

        return SMSResult(ok=ok, provider_id=provider_id, status=status, raw=raw)

    except Exception as e:
        logger.exception("SMSMODE exception")
        return SMSResult(ok=False, provider_id=None, status=f"EXC:{e}", raw={})

