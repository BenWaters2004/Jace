from __future__ import annotations

import re
from fnmatch import fnmatch

from jace.control.windows import WindowInfo


ABSOLUTELY_BLOCKED_PROCESS_PATTERNS = {
    "1password*.exe",
    "bitwarden*.exe",
    "keepass*.exe",
    "keepassxc*.exe",
    "enpass*.exe",
    "authy*.exe",
    "proton-pass*.exe",
    "credentialuibroker.exe",
    "logonui.exe",
    "lockapp.exe",
    "consent.exe",
}

SENSITIVE_TITLE_RE = re.compile(
    r"\b(?:password|passcode|sign[ -]?in|log[ -]?in|authentication|authenticator|"
    r"verification code|security code|one[ -]?time code|otp|2fa|mfa|payment|checkout|"
    r"billing|bank(?:ing)?|wallet|card details?|credit card|debit card|security key|"
    r"passkey|private key|secret|credentials?|recovery code)\b",
    re.IGNORECASE,
)

SENSITIVE_INTENT_RE = re.compile(
    r"\b(?:submit|send|post|publish|purchase|buy|pay|checkout|delete|remove|erase|"
    r"uninstall|install|sign[ -]?in|log[ -]?in|authenticate|confirm|accept|approve|"
    r"authorize|transfer|upload|share|invite|close without saving|discard)\b",
    re.IGNORECASE,
)

HIGH_RISK_TEXT_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:password|passwd|api[_ -]?key|secret[_ -]?key|access[_ -]?token)\s*[:=]\s*\S+", re.IGNORECASE),
]

SENSITIVE_KEY_COMBINATIONS = {
    ("alt", "f4"),
    ("ctrl", "w"),
    ("ctrl", "shift", "w"),
    ("ctrl", "enter"),
    ("shift", "enter"),
    ("win", "r"),
    ("winleft", "r"),
    ("winright", "r"),
    ("ctrl", "shift", "esc"),
}



def process_pattern_is_too_broad(pattern: str) -> bool:
    normalized = pattern.strip().casefold()
    # Phase 9 policies are application boundaries, not machine-wide grants.
    # Reject patterns that effectively match every ordinary Windows process.
    return normalized in {"*", "*.*", "*.exe", "**", "?*", "*exe"}

def process_is_absolutely_blocked(process_name: str) -> bool:
    name = process_name.casefold()
    return any(fnmatch(name, pattern.casefold()) for pattern in ABSOLUTELY_BLOCKED_PROCESS_PATTERNS)


def window_is_sensitive(window: WindowInfo | None) -> bool:
    if window is None:
        return False
    if process_is_absolutely_blocked(window.process_name):
        return True
    return bool(SENSITIVE_TITLE_RE.search(window.title))


def intent_is_sensitive(intent: str) -> bool:
    return bool(SENSITIVE_INTENT_RE.search(intent or ""))


def text_contains_high_risk_secret(text: str) -> bool:
    if any(pattern.search(text) for pattern in HIGH_RISK_TEXT_PATTERNS):
        return True

    # A bare 13-19 digit payment-card-like value should never be typed by the
    # model. This deliberately ignores spaces/dashes before applying Luhn.
    for candidate in re.findall(r"(?:\d[ -]?){13,19}", text):
        digits = re.sub(r"\D", "", candidate)
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return True
    return False


def key_sequence_is_sensitive(keys: list[str]) -> bool:
    normalized = tuple(key.casefold() for key in keys)
    return normalized in SENSITIVE_KEY_COMBINATIONS or "enter" in normalized


def _luhn_valid(value: str) -> bool:
    if not value.isdigit():
        return False
    total = 0
    parity = len(value) % 2
    for index, character in enumerate(value):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0
