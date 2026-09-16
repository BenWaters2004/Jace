from __future__ import annotations

# JACE_STEP4C3_EMAIL_WRITE_COMMON

import html
import re
from email.utils import parseaddr
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MAX_RECIPIENTS_PER_FIELD = 50
MAX_SUBJECT_CHARS = 998
MAX_BODY_CHARS = 100_000


def _valid_email_address(value: str) -> str:
    cleaned = value.strip()

    if not cleaned:
        raise ValueError("Email address cannot be empty.")

    _, parsed = parseaddr(cleaned)

    if (
        not parsed
        or "@" not in parsed
        or parsed.startswith("@")
        or parsed.endswith("@")
    ):
        raise ValueError(
            f"Invalid email address: {cleaned}"
        )

    local, _, domain = parsed.rpartition("@")

    if not local or "." not in domain:
        # Local development/test domains are still allowed if they contain a
        # valid-looking hostname. Reject only clearly malformed domains.
        if not local or not domain:
            raise ValueError(
                f"Invalid email address: {cleaned}"
            )

    return cleaned


def _validate_recipient_list(
    values: list[str],
) -> list[str]:
    if len(values) > MAX_RECIPIENTS_PER_FIELD:
        raise ValueError(
            f"At most {MAX_RECIPIENTS_PER_FIELD} recipients are allowed "
            "per recipient field."
        )

    seen: set[str] = set()
    result: list[str] = []

    for value in values:
        cleaned = _valid_email_address(
            value
        )
        key = parseaddr(cleaned)[1].casefold()

        if key in seen:
            continue

        seen.add(key)
        result.append(cleaned)

    return result


def plain_text_from_html(
    value: str,
) -> str:
    text = re.sub(
        r"(?is)<(?:script|style).*?>.*?</(?:script|style)>",
        " ",
        value,
    )
    text = re.sub(
        r"(?s)<[^>]+>",
        " ",
        text,
    )
    text = html.unescape(text)
    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )
    text = re.sub(
        r"\n\s*\n+",
        "\n\n",
        text,
    )
    return text.strip()


class EmailComposeInput(BaseModel):
    to: list[str] = Field(
        min_length=1,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description="Primary recipient email addresses.",
    )
    cc: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description="Optional CC recipient email addresses.",
    )
    bcc: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description="Optional BCC recipient email addresses.",
    )
    subject: str = Field(
        default="",
        max_length=MAX_SUBJECT_CHARS,
        description="Email subject.",
    )
    body: str = Field(
        default="",
        max_length=MAX_BODY_CHARS,
        description="Complete message body that will be drafted.",
    )
    body_format: Literal[
        "text",
        "html",
    ] = Field(
        default="text",
        description="Whether body contains plain text or HTML.",
    )

    @field_validator(
        "to",
        "cc",
        "bcc",
    )
    @classmethod
    def validate_recipients(
        cls,
        value: list[str],
    ) -> list[str]:
        return _validate_recipient_list(
            value
        )


class EmailSendInput(BaseModel):
    draft_id: str | None = Field(
        default=None,
        max_length=2_000,
        description=(
            "Existing provider draft ID to send. If supplied, recipients, "
            "subject and body are taken from the existing draft."
        ),
    )
    to: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description=(
            "Primary recipients for a new message. Required when draft_id "
            "is not supplied."
        ),
    )
    cc: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description="Optional CC recipients for a new message.",
    )
    bcc: list[str] = Field(
        default_factory=list,
        max_length=MAX_RECIPIENTS_PER_FIELD,
        description="Optional BCC recipients for a new message.",
    )
    subject: str = Field(
        default="",
        max_length=MAX_SUBJECT_CHARS,
        description="Email subject for a new message.",
    )
    body: str = Field(
        default="",
        max_length=MAX_BODY_CHARS,
        description="Complete message body for a new message.",
    )
    body_format: Literal[
        "text",
        "html",
    ] = Field(
        default="text",
        description="Whether body contains plain text or HTML.",
    )

    @field_validator(
        "to",
        "cc",
        "bcc",
    )
    @classmethod
    def validate_recipients(
        cls,
        value: list[str],
    ) -> list[str]:
        return _validate_recipient_list(
            value
        )

    @model_validator(
        mode="after",
    )
    def validate_send_mode(
        self,
    ) -> "EmailSendInput":
        if self.draft_id:
            self.draft_id = (
                self.draft_id.strip()
            )

            if not self.draft_id:
                raise ValueError(
                    "draft_id cannot be blank."
                )

            return self

        if not (
            self.to
            or self.cc
            or self.bcc
        ):
            raise ValueError(
                "A new email must have at least one recipient."
            )

        return self


def recipients_summary(
    data: EmailComposeInput | EmailSendInput,
) -> dict[str, list[str]]:
    return {
        "to": list(data.to),
        "cc": list(data.cc),
        "bcc": list(data.bcc),
    }
