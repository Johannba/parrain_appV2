# common/phone_utils.py
from __future__ import annotations
from typing import Optional, Tuple, Dict
import re

E164_RE = re.compile(r"^\+\d{6,15}$")

# DOM/TOM -> code pays cible
# Guadeloupe(+590), Martinique(+596), Guyane(+594), Réunion(+262), Mayotte(+262), Haïti(+509)
DOM_PREFIXES = {
    # Guadeloupe
    "0590": "+590", "0690": "+590",
    # Martinique
    "0596": "+596", "0696": "+596",
    # Guyane
    "0594": "+594", "0694": "+594",
    # Réunion
    "0262": "+262", "0692": "+262", "0693": "+262",
    # Mayotte
    "0269": "+262", "0639": "+262",
}

def _digits_plus(s: str) -> str:
    return re.sub(r"[^\d\+]", "", s or "")

def _region_from_cc(e164: str) -> str:
    if e164.startswith("+33"):  return "FR"
    if e164.startswith("+590"): return "GP"  # Guadeloupe
    if e164.startswith("+596"): return "MQ"  # Martinique
    if e164.startswith("+594"): return "GF"  # Guyane
    if e164.startswith("+262"): return "RE"  # Réunion/Mayotte (indistinct)
    if e164.startswith("+509"): return "HT"  # Haïti
    if e164.startswith("+20"):  return "EG"  # Égypte
    return "INTL"

def normalize_msisdn(raw: str, *, default_region: str = "FR") -> Tuple[Optional[str], Dict]:
    """
    Retourne (to_provider, meta) où:
      - to_provider = chaîne chiffres SANS '+' (prête pour provider tolérant),
      - meta = {"input": str, "region_used": str, "e164": "+…", "is_valid": bool, "reason": str}

    Règles robustes:
      - '00' -> '+'
      - Si déjà E.164, on renvoie tel quel
      - Si 10 chiffres et commence par '0' => FR/DOM (force +33 / +590 / +596 / +594 / +262)
      - Si 9 chiffres et commence par '6' ou '7' => mobile FR sans '0' => +33
      - Si 8 chiffres => Haïti local => +509
      - Sinon => on tente par défaut (default_region) mais on n’impose PAS +20 aux 06/07 FR
    """
    cleaned = _digits_plus(raw).replace(" ", "")
    meta: Dict = {"input": raw or "", "region_used": default_region, "e164": "", "is_valid": False, "reason": ""}

    if not cleaned:
        meta["reason"] = "empty"
        return None, meta

    # 00 => +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    # Déjà E.164
    if E164_RE.match(cleaned):
        meta["e164"] = cleaned
        meta["region_used"] = _region_from_cc(cleaned)
        meta["is_valid"] = True
        meta["reason"] = "already_e164"
        return cleaned.lstrip("+"), meta

    # --- Heuristique FR/DOM prioritaire si 10 chiffres locaux ---
    if cleaned.startswith("0") and len(cleaned) == 10 and cleaned.isdigit():
        n = cleaned[1:]  # supprime le 0
        # DOM : 059x / 069x / 026x / 0639 / 0269
        for pfx, cc in DOM_PREFIXES.items():
            if cleaned.startswith(pfx):
                e164 = f"{cc}{n}"
                meta.update({"e164": "+" + e164, "region_used": _region_from_cc("+" + e164),
                             "is_valid": True, "reason": "dom_national_10"})
                return e164, meta
        # Métropole
        e164 = f"33{n}"
        meta.update({"e164": "+" + e164, "region_used": "FR", "is_valid": True, "reason": "fr_national_10"})
        return e164, meta

    # 9 chiffres mobiles FR (sans 0 initial)
    if len(cleaned) == 9 and cleaned.isdigit() and cleaned[0] in ("6", "7"):
        e164 = f"33{cleaned}"
        meta.update({"e164": "+" + e164, "region_used": "FR", "is_valid": True, "reason": "fr_mobile_9"})
        return e164, meta

    # Haïti 8 chiffres locaux
    if len(cleaned) == 8 and cleaned.isdigit():
        e164 = f"509{cleaned}"
        meta.update({"e164": "+" + e164, "region_used": "HT", "is_valid": True, "reason": "ht_local_8"})
        return e164, meta

    # DOM saisis sans '0' (rare, 9 chiffres après indicatif local)
    if len(cleaned) == 9 and cleaned.isdigit():
        for dom3, cc in {k[:3]: v for k, v in DOM_PREFIXES.items()}.items():
            if cleaned.startswith(dom3):
                e164 = f"{cc.lstrip('+')}{cleaned}"
                meta.update({"e164": "+" + e164, "region_used": _region_from_cc("+" + e164),
                             "is_valid": True, "reason": "dom_local_9"})
                return e164, meta

    # Fallback “région par défaut” (on ne force pas +20 pour des 06/07 FR)
    # Si on arrive ici et que ça ressemble à un mobile/trunk FR mal saisi, laisse invalide.
    if default_region.upper() == "EG" and cleaned.isdigit():
        # EG typique: 11 chiffres, commence par 1 ou 01
        n = cleaned.lstrip("0")
        if len(n) == 11 and n[0] == "1":
            e164 = f"20{n}"
            meta.update({"e164": "+" + e164, "region_used": "EG", "is_valid": True, "reason": "eg_local"})
            return e164, meta

    # Rien de concluant
    meta["reason"] = "unhandled_pattern"
    return None, meta
