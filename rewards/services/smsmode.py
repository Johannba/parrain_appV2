# rewards/services/smsmode.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
import logging
import re
import requests
from django.conf import settings
from common.phone_utils import normalize_msisdn  # retourne (to_digits, meta)

logger = logging.getLogger(__name__)

__all__ = [
    "SMSPayload",
    "SMSResult",
    "build_reward_sms_text",
    "_build_smsmode_url",
    "send_sms",
    "normalize_msisdn",
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
# Helpers
# =========================

def _to_provider_digits(raw_number: str) -> Tuple[str, Dict[str, Any]]:
    """
    Normalise un numéro pour l'API smsmode : renvoie uniquement des chiffres.
    S'appuie sur common.phone_utils.normalize_msisdn -> (to_digits, meta).
    """
    to_digits, meta = normalize_msisdn(
        raw_number,
        default_region=getattr(settings, "SMS_DEFAULT_REGION", "FR"),
    )

    # Priorité : to_digits (déjà sans '+'), sinon meta['e164'] sans '+', sinon digits du brut
    final = to_digits or (meta.get("e164") or "").lstrip("+") or re.sub(r"\D", "", raw_number or "")
    return final, meta

# =========================
# Envoi
# =========================

def send_sms(payload: SMSPayload) -> SMSResult:
    """
    Envoi via smsmode.
    Auth: header 'X-Api-Key: <API_KEY>'
    Endpoint: https://rest.smsmode.com/sms/v1/messages
    Body:
      {
        "recipient": {"to": "33646267551"},
        "body": {"text": "message"},
        "from": "ParrainApp"  # optionnel selon contrat
      }
    """
    if settings.SMSMODE.get("DRY_RUN"):
        logger.info("[SMSMODE DRY-RUN] %s", payload)
        return SMSResult(ok=True, provider_id=None, status="DRY_RUN", raw={"dry_run": True})

    url = _build_smsmode_url()

    headers = {
        "X-Api-Key": settings.SMSMODE["API_KEY"],   # Auth correcte
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Normalisation : on envoie des CHIFFRES (sans '+')
    final_to, meta = _to_provider_digits(payload.to)
    if not final_to:
        logger.error("SMSMODE: numéro invalide après normalisation (%s) meta=%s", payload.to, meta)
        return SMSResult(ok=False, provider_id=None, status="INVALID_NUMBER", raw={"meta": meta})

    if meta.get("e164"):
        logger.info("SMSMODE normalize: raw=%s -> e164=%s -> to=%s", payload.to, meta["e164"], final_to)

    data: Dict[str, Any] = {
        "recipient": {"to": final_to},
        "body": {"text": payload.text},
    }
    if payload.sender:
        data["from"] = payload.sender

    logger.info("SMSMODE POST %s to=%s sender=%s", url, final_to, payload.sender or "")

    try:
        timeout = int(settings.SMSMODE.get("TIMEOUT", 10))
        resp = requests.post(url, headers=headers, json=data, timeout=timeout)

        # JSON sûr
        raw: Dict[str, Any]
        try:
            raw = resp.json()
        except Exception:
            raw = {"text": resp.text}

        ok = 200 <= resp.status_code < 300  # 201 attendu en général

        # id de message (peut être messageId ou messageIds[])
        provider_id: Optional[str] = None
        if isinstance(raw.get("messageIds"), list) and raw["messageIds"]:
            provider_id = raw["messageIds"][0]
        else:
            provider_id = raw.get("messageId")

        # statut : objet ou chaîne
        status_val = raw.get("status")
        if isinstance(status_val, dict):
            status_str = status_val.get("value") or status_val.get("status") or ("OK" if ok else f"HTTP_{resp.status_code}")
        else:
            status_str = status_val or ("OK" if ok else f"HTTP_{resp.status_code}")

        if not ok:
            logger.error("SMSMODE error: http=%s raw=%s url=%s", resp.status_code, raw, url)

        return SMSResult(ok=ok, provider_id=provider_id, status=status_str, raw=raw)

    except Exception as e:
        logger.exception("SMSMODE exception")
        return SMSResult(ok=False, provider_id=None, status=f"EXC:{e}", raw={})
