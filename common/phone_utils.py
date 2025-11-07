# common/phone_utils.py
from typing import Tuple, Optional, Dict
import re

_DIGITS = re.compile(r"\D+")

# Pour DOM/TOM : mapping des préfixes nationaux (après le 0) -> indicatif pays
# Certains préfixes mobiles (069x/0639) mappent vers l'indicatif DOM correct.
_DOM_MAP = {
    # Guadeloupe
    "590": "590", "690": "590",
    # Martinique
    "596": "596", "696": "596",
    # Guyane
    "594": "594", "694": "594",
    # Réunion
    "262": "262", "692": "262", "693": "262",
    # Mayotte -> +262
    "269": "262", "639": "262",
}

def _only_digits(s: str) -> str:
    return _DIGITS.sub("", s or "")

def normalize_msisdn(raw: str, *, default_region: str = "FR") -> Tuple[Optional[str], Dict]:
    """
    Retourne (to_digits, meta) :
      - to_digits : E.164 SANS '+' (ex: '33646267551', '590690123456', '50912345678')
      - meta : dict {"input","region_used","e164","+CC...","is_valid":bool,"reason":str}
    Règles couvertes : FR métropole (06/07/01..05), DOM/TOM (0xxx / 9-chiffres sans 0),
    Haïti (8 chiffres locaux), formats internationaux '00' ou déjà '+', ainsi que
    'intl_no_plus' (ex: 336..., 262...). Ne dépend pas de default_region pour les motifs FR/DOM/HT.
    """
    meta: Dict[str, Optional[str] | bool] = {
        "input": raw,
        "region_used": default_region,
        "e164": "",
        "is_valid": False,
        "reason": "",
    }

    s = (raw or "").strip()
    if not s:
        meta["reason"] = "empty"
        return None, meta

    # 1) E.164 déjà présent (+CC...)
    if s.startswith("+"):
        digits = _only_digits(s)  # enlève le '+'
        if 6 <= len(digits) <= 15:
            meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "already_e164", "region_used": "INTL"})
            return digits, meta
        meta["reason"] = "bad_e164_len"
        return None, meta

    # 2) International avec '00'
    if s.startswith("00"):
        digits = _only_digits(s[2:])
        if 6 <= len(digits) <= 15:
            meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "intl_00", "region_used": "INTL"})
            return digits, meta
        meta["reason"] = "bad_intl_00_len"
        return None, meta

    # 3) FR/DOM national 10 chiffres (commence par 0)
    ds = _only_digits(s)
    if len(ds) == 10 and ds.startswith("0"):
        n = ds[1:]  # on enlève le 0
        # DOM/TOM ?
        for dom_prefix, cc in _DOM_MAP.items():
            if n.startswith(dom_prefix):
                digits = f"{cc}{n}"
                meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "dom_national_10", "region_used": "INTL"})
                return digits, meta
        # Métropole
        # Fixe 01..05
        if n[0] in "12345":
            digits = f"33{n[0]}{n[1:]}"
            meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "fr_national_10", "region_used": "FR"})
            return digits, meta
        # Mobiles 06/07
        if n[0] in ("6", "7"):
            digits = f"33{n}"
            meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "fr_national_10", "region_used": "FR"})
            return digits, meta
        meta["reason"] = "unhandled_fr_dom_10"
        return None, meta

    # 4) DOM local 9 chiffres sans '0' initial (ex: 590123456, 690123456, etc.)
    if len(ds) == 9 and ds.isdigit():
        p3 = ds[:3]
        # règles par ordre de spécificité (mobiles 690/696/694/692/693/269/639)
        if ds.startswith("690"):
            digits = f"590{ds}"
        elif ds.startswith("696"):
            digits = f"596{ds}"
        elif ds.startswith("694"):
            digits = f"594{ds}"
        elif ds.startswith(("692", "693", "262")):
            digits = f"262{ds}"
        elif ds.startswith(("269", "639")):
            digits = f"262{ds}"
        elif p3 in ("590", "596", "594"):
            digits = f"{p3}{ds}"
        else:
            # FR mobile sans 0 (9 chiffres commençant par 6/7)
            if ds[0] in ("6", "7"):
                digits = f"33{ds}"
                meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "fr_mobile_9", "region_used": "FR"})
                return digits, meta
            meta["reason"] = "unhandled_pattern"
            return None, meta
        meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "dom_local_9", "region_used": "INTL"})
        return digits, meta

    # 5) Haïti : 8 chiffres locaux
    if len(ds) == 8 and ds.isdigit():
        digits = f"509{ds}"
        meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "ht_local_8", "region_used": "HT"})
        return digits, meta

    # 6) International "sans plus" (ex: 336..., 262..., 2010..., etc.)
    if 6 <= len(ds) <= 15:
        digits = ds
        meta.update({"e164": f"+{digits}", "is_valid": True, "reason": "intl_no_plus", "region_used": "INTL"})
        return digits, meta

    meta["reason"] = "unhandled"
    return None, meta
