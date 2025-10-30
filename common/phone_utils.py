# common/phone_utils.py
from __future__ import annotations
import re
from typing import Optional, Tuple, Dict

import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException

# Préfixes DOM/TOM -> régions libphonenumber (indices "region code")
FR_DOM_PREFIX_MAP = {
    "0590": "GP", "0690": "GP",  # Guadeloupe (+590)
    "0594": "GF", "0694": "GF",  # Guyane (+594)
    "0596": "MQ", "0696": "MQ",  # Martinique (+596)
    "0262": "RE", "0692": "RE", "0693": "RE",  # Réunion (+262)
    "0269": "YT", "0691": "YT",  # Mayotte (+262)
}

# Mobiles Égypte (sans indicatif) : 010, 011, 012, 015
EG_LOCAL_MOBILE_PREFIXES = ("010", "011", "012", "015")


def normalize_msisdn(raw: str, *, default_region: str = "FR") -> Tuple[Optional[str], Dict]:
    """
    Normalise un numéro utilisateur vers MSISDN pour SMSMODE:
      - Accepte +E.164, 00..., locaux (FR, DOM/TOM, EG)
      - Retourne MSISDN sans '+', ex: '2011...', '336...', '212...'
    Renvoie: (msisdn_str_or_None, meta_dict)
    """
    meta = {"input": raw, "region_used": None, "e164": None, "is_valid": False, "reason": ""}

    if not raw:
        meta["reason"] = "empty"
        return None, meta

    s = (raw or "").strip()
    # 00 -> +
    if s.startswith("00"):
        s = "+" + s[2:]

    # Nettoyage pour heuristiques
    digits = re.sub(r"\D+", "", s)
    region = (default_region or "FR").upper()

    # Heuristique DOM/TOM (si local sans '+')
    if not s.startswith("+") and digits:
        for pref, reg in FR_DOM_PREFIX_MAP.items():
            if digits.startswith(pref):
                region = reg
                break

        # Heuristique Égypte (formats locaux 010/011/012/015)
        if region == "FR":  # si pas overridé ci-dessus
            if any(digits.startswith(p) for p in EG_LOCAL_MOBILE_PREFIXES) and 9 <= len(digits) <= 11:
                region = "EG"

    # Parse
    num = None
    try:
        num = phonenumbers.parse(s, region if not s.startswith("+") else None)
    except NumberParseException:
        # Tentative forcée en +E.164 si on a des digits
        if not s.startswith("+") and digits:
            try:
                num = phonenumbers.parse("+" + digits, None)
            except NumberParseException as e:
                meta["reason"] = f"parse_error:{e}"
                return None, meta
        else:
            meta["reason"] = "parse_error"
            return None, meta

    if not phonenumbers.is_possible_number(num) or not phonenumbers.is_valid_number(num):
        meta["reason"] = "invalid_number"
        return None, meta

    e164 = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)  # ex: +2011...
    meta.update({"e164": e164, "region_used": region, "is_valid": True})
    return e164.lstrip("+"), meta  # SMSMODE: sans '+'
