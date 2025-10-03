# core/utils/phones.py
import re
import phonenumbers
from phonenumbers import PhoneNumberFormat, NumberParseException

# France + DROM (tu peux étendre si besoin)
ALLOWED_REGIONS_DEFAULT = ("FR", "GF", "MQ", "GP", "RE")

_CLEAN_RE = re.compile(r"[^\d\+]")
_ONLY_DIGITS_RE = re.compile(r"\D+")

# Indicatifs saisis "nus" tolérés sans '+'
BARE_COUNTRY_CODES = ("33", "590", "594", "596", "262")


def _fallback_dom_fr_to_e164(digits: str) -> str | None:
    """
    Tolérance DOM/FR si libphonenumber rejette mais que le motif local est plausible.
    Règle : format local FR/DOM = 10 chiffres : 0 + (préfixe) + 6 chiffres.
    """
    mapping = {
        # Guadeloupe
        "0590": "+590590", "0690": "+590690",
        # Guyane
        "0594": "+594594", "0694": "+594694",
        # Martinique
        "0596": "+596596", "0696": "+596696",
        # Réunion
        "0262": "+262262", "0692": "+262692", "0693": "+262693",
    }

    if len(digits) == 10 and digits.startswith("0"):
        for pfx, e164pfx in mapping.items():
            if digits.startswith(pfx):
                rest = digits[len(pfx):]
                if len(rest) == 6 and rest.isdigit():
                    return f"{e164pfx}{rest}"  # ex: 0594 50 72 05 -> +594594507205
        # FR métropole (0X + 8 chiffres) -> +33 X + 8 chiffres
        if digits[1:].isdigit() and digits[1] != "0":
            return "+33" + digits[1:]
    return None


def to_e164(phone_raw: str, regions=ALLOWED_REGIONS_DEFAULT) -> str:
    """
    Parse et normalise un numéro en E.164, en tolérant :
    - 00 comme préfixe international,
    - indicatif pays saisi sans '+',
    - formats locaux FR/DOM (fallback si libphonenumber rejette).
    """
    if not phone_raw:
        raise ValueError("Numéro requis.")

    raw = phone_raw.strip()
    cleaned = _CLEAN_RE.sub("", raw)

    # 00 -> +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    # 1) International direct
    if cleaned.startswith("+"):
        try:
            num = phonenumbers.parse(cleaned, None)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
        except NumberParseException:
            pass

    # 2) Indicatif nu sans '+'
    digits_only = _ONLY_DIGITS_RE.sub("", raw)
    for cc in BARE_COUNTRY_CODES:
        if digits_only.startswith(cc) and not raw.startswith(("+", "00")):
            try:
                num = phonenumbers.parse("+" + digits_only, None)
                if phonenumbers.is_valid_number(num):
                    return phonenumbers.format_number(num, PhoneNumberFormat.E164)
            except NumberParseException:
                pass

    # 3) Essais par régions (formats locaux)
    for region in regions:
        try:
            num = phonenumbers.parse(raw, region)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
        except NumberParseException:
            continue

    # 4) Re-parse sur 'cleaned'
    for region in regions:
        try:
            num = phonenumbers.parse(cleaned, region)
            if phonenumbers.is_valid_number(num):
                return phonenumbers.format_number(num, PhoneNumberFormat.E164)
        except NumberParseException:
            continue

    # 5) ✅ Fallback tolérant DOM/FR
    fb = _fallback_dom_fr_to_e164(_ONLY_DIGITS_RE.sub("", raw))
    if fb:
        return fb

    raise ValueError(
        "Numéro invalide. Formats acceptés : France/DOM (+33, +594, +596, +590, +262)."
    )
