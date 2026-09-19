from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    r".*?"
    r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_GITHUB = re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b", re.IGNORECASE)
_AWS = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_OPENAI_STYLE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+-])"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
_ASSIGNED_SECRET = re.compile(
    r"""(?ix)
    \b(?P<key>
        password|passwd|api[_-]?key|client[_-]?secret|
        access[_-]?token|refresh[_-]?token
    )\b
    (?P<separator>\s*[:=]\s*)
    (?P<value>
        ["'][^"'\r\n]{8,}["']
        |
        [A-Za-z0-9._~+/=-]{12,}
    )
    """
)


@dataclass(slots=True)
class PrivacyTransform:
    aliases: dict[tuple[str, str], str] = field(default_factory=dict)
    replacement_count: int = 0

    def _alias(self, kind: str, value: str) -> str:
        key = (kind, value.casefold())
        if key not in self.aliases:
            index = 1 + sum(
                1 for existing_kind, _ in self.aliases
                if existing_kind == kind
            )
            self.aliases[key] = f"<{kind.upper()}_{index}>"
        return self.aliases[key]

    def protect_text(self, text: str) -> str:
        result = text

        for pattern, replacement in (
            (_PRIVATE_KEY_BLOCK, "<SECRET:PRIVATE_KEY>"),
            (_BEARER, "<SECRET:BEARER_TOKEN>"),
            (_JWT, "<SECRET:JWT>"),
            (_GITHUB, "<SECRET:GITHUB_TOKEN>"),
            (_AWS, "<SECRET:AWS_ACCESS_KEY>"),
            (_OPENAI_STYLE, "<SECRET:API_KEY>"),
        ):
            def repl(_match, value=replacement):
                self.replacement_count += 1
                return value
            result = pattern.sub(repl, result)

        def assigned(match: re.Match[str]) -> str:
            self.replacement_count += 1
            return (
                f"{match.group('key')}"
                f"{match.group('separator')}"
                "<SECRET:REDACTED>"
            )

        result = _ASSIGNED_SECRET.sub(assigned, result)

        def email(match: re.Match[str]) -> str:
            self.replacement_count += 1
            return self._alias("email", match.group(0))

        def phone(match: re.Match[str]) -> str:
            self.replacement_count += 1
            return self._alias("phone", match.group(0))

        result = _EMAIL.sub(email, result)
        result = _PHONE.sub(phone, result)
        return result

    def protect_payload(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.protect_text(value)
        if isinstance(value, dict):
            return {
                key: self.protect_payload(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.protect_payload(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.protect_payload(item) for item in value)
        return value
