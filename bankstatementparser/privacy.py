# SPDX-License-Identifier: Apache-2.0 OR MIT
# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.

"""Conservative field redaction for statement displays and explicit exports."""

from collections.abc import Mapping
from typing import Any

PII_FIELDS = (
    "address",
    "iban",
    "account",
    "name",
    "bic",
    "debtor",
    "creditor",
    "dbtr",
    "cdtr",
    "description",
    "reference",
    "counterparty",
    "rmtinf",
    "raw_source",
    "transaction_id",
    "endtoendid",
    "end_to_end_id",
    "acctsvcrref",
    "normalized_description",
    "initgpty",
    "initiating_party",
    "msgid",
    "message_id",
    "pmtinfid",
    "pmt_inf_id",
    "instrid",
    "statementid",
    "statement_id",
)


def redact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Mask identity and free-text fields while retaining amounts and dates.

    Narratives may contain names or account numbers, so masking whole fields
    is safer than trying to recognize every possible personal identifier.
    This is display redaction, not a guarantee of irreversible anonymization.
    """
    return {
        key: "***REDACTED***"
        if value is not None
        and any(token in key.lower() for token in PII_FIELDS)
        else value
        for key, value in record.items()
    }
