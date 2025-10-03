# rewards/services/smsmode.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
import json
import logging
import re
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

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
# Normalisation E.164 (FR + DROM + HT)
# =========================

E164_RE = re.compile(r"^\+\d{6,15}$")

def _digits_plus(s: str) -> str:
    """Garde uniquement chiffres et +."""
    return re.sub(r"[^\d\+]", "", s or "")

def normalize_msisdn(phone: str) -> str:
    """
    Normalise en E.164 pour :
      - France métropolitaine : 0X XX XX XX XX  -> +33 X...
      - Guadeloupe : 0590/0690 -> +590590... / +590690...
      - Martinique : 0596/0696 -> +596596... / +596696...
      - Guyane : 0594/0694     -> +594594... / +594694...
      - La Réunion : 0262/0692/0693 -> +262262... / +262692... / +262693...
      - Mayotte : 0269/0639        -> +262269... / +262639...
      - Haïti : 8 chiffres locaux  -> +509XXXXXXXX
    Règles :
      - '00' prefix => remplacé par '+'
      - si déjà E.164, renvoyé tel quel
      - si commence par indicatif sans '+', on ajoute '+'
    """
    raw = (phone or "").strip()
    p = _digits_plus(raw).replace(" ", "")

    # 00 => +
    if p.startswith("00"):
        p = "+" + p[2:]

    # déjà E.164 ?
    if E164_RE.match(p):
        return p

    # indicatifs DOM/HT sans '+'
    for cc in ("590", "596", "594", "262", "509"):
        if p.startswith(cc) and p[len(cc):].isdigit():
            return f"+{p}"

    # France/DOM formats nationaux (10 chiffres, commence par 0)
    if p.startswith("0") and len(p) == 10 and p.isdigit():
        n = p[1:]  # sans le 0
        # DOM fixes/mobiles
        if n.startswith(("590", "690")):  # Guadeloupe
            return f"+590{n}"
        if n.startswith(("596", "696")):  # Martinique
            return f"+596{n}"
        if n.startswith(("594", "694")):  # Guyane
            return f"+594{n}"
        if n.startswith(("262", "692", "693")):  # Réunion
            return f"+262{n}"
        if n.startswith(("269", "639")):  # Mayotte
            return f"+262{n}"  # E.164 Mayotte utilise +262

        # Métropole
        if n[0] in "12345":      # 01..05 -> +331..+335
            return f"+33{n[0]}{n[1:]}"
        if n[0] == "6":          # 06 -> +336
            return f"+33{n}"
        if n[0] == "7":          # 07 -> +337
            return f"+33{n}"

    # Haïti local sans trunk (8 chiffres)
    if len(p) == 8 and p.isdigit():
        return f"+509{p}"

    # 9 chiffres commençant par indicatifs DOM
    if len(p) == 9 and p.isdigit():
        if p.startswith(("590", "596", "594", "262")):
            return f"+{p[:3]}{p}"
        if p.startswith("690"):
            return f"+590{p}"
        if p.startswith("696"):
            return f"+596{p}"
        if p.startswith("694"):
            return f"+594{p}"
        if p.startswith(("692", "693")):
            return f"+262{p}"
        if p.startswith(("269", "639")):
            return f"+262{p}"

    # 9 chiffres métropole mobiles sans 0
    if len(p) == 9 and p.isdigit() and p[0] in ("6", "7"):
        return f"+33{p}"

    # Rien de concluant => renvoyer brut (le provider peut refuser si invalide)
    return raw

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

    data: Dict[str, Any] = {
        "recipient": {"to": payload.to},   # <- champ attendu
        "body": {"text": payload.text},    # <- champ attendu
    }
    if payload.sender:
        data["from"] = payload.sender      # optionnel selon votre contrat

    logger.info("SMSMODE POST %s to=%s sender=%s", url, payload.to, payload.sender or "")

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
