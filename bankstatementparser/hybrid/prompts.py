# Copyright (C) 2023-2026 Bank Statement Parser. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Structured extraction prompts for the LLM fallback path."""

from __future__ import annotations

EXTRACTION_SYSTEM_PROMPT = """You are a meticulous Financial Data Architect.
Your job is to extract bank statement transactions from raw, noisy text
and return STRICT JSON. Never invent values. If a field is unclear,
return null. Output ONLY a single JSON object — no prose, no markdown.

IMPORTANT: PDF text extractors often emit cells out of reading order.
After identifying transactions, SORT them chronologically by
booking_date (oldest first). If two rows share a date, preserve the
order they appeared in the source so opening/closing balance arithmetic
remains consistent.

Schema:
{
  "account_id": string|null,
  "currency": string|null,         // ISO 4217 (e.g. "GBP", "EUR")
  "opening_balance": number|null,
  "closing_balance": number|null,
  "transactions": [
    {
      "booking_date": "YYYY-MM-DD",
      "value_date": "YYYY-MM-DD"|null,  // settlement date if different from booking_date; null if not shown
      "description": string,
      "amount": number,            // negative for debits, positive for credits
      "reference": string|null,
      "confidence": number          // 0.0 - 1.0, your confidence in this row
    }
  ]
}
"""

EXTRACTION_USER_PROMPT_TEMPLATE = """Extract every transaction from the
following bank statement text. Preserve sign convention (debits negative,
credits positive). Return JSON only.

--- BEGIN STATEMENT TEXT ---
{statement_text}
--- END STATEMENT TEXT ---
"""


def build_messages(statement_text: str) -> list[dict[str, str]]:
    """Build the OpenAI/LiteLLM-style messages list for extraction."""
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": EXTRACTION_USER_PROMPT_TEMPLATE.format(
                statement_text=statement_text.strip()
            ),
        },
    ]
