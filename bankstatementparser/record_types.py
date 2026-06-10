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

"""Typed records shared by parser implementations."""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class BalanceRecord(TypedDict, total=False):
    Amount: Decimal
    Currency: str | None
    Code: str | None
    Description: str | None
    DrCr: str | None
    Date: str | None
    AccountId: str | None


class TransactionRecord(TypedDict, total=False):
    Amount: Decimal
    Currency: str | None
    DrCr: str | None
    Debtor: str | None
    Creditor: str | None
    Reference: str | None
    ValDt: str | None
    BookgDt: str | None
    AccountId: str | None
    DebtorAddress: str | None
    CreditorAddress: str | None
    date: str | None
    description: str | None
    amount: Decimal | None
    currency: str | None
    balance: object
    account_id: str | None
    transaction_id: str | None
    transaction_type: str | None


class PaymentRecord(TypedDict, total=False):
    MsgId: str | None
    CreDtTm: str | None
    NbOfTxs: str | None
    InitgPty: str | None
    PmtInfId: str | None
    PmtMtd: str | None
    CtrlSum: str | None
    ReqdExctnDt: str | None
    ChrgBr: str | None
    DbtrNm: str | None
    DbtrIBAN: str | None
    DbtrBIC: str | None
    EndToEndId: str | None
    InstdAmt: str | None
    Currency: str | None
    CdtrBIC: str | None
    CdtrNm: str | None
    RmtInf: str | None


class StatementStatsRecord(TypedDict, total=False):
    StatementId: str | None
    AccountId: str | None
    StatementCreated: str | None
    NumTransactions: int
    NetAmount: Decimal


class SummaryRecord(TypedDict, total=False):
    account_id: str | None
    statement_date: str | None
    transaction_count: int
    total_amount: Decimal
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    currency: str | None
    message_id: str | None
    initiating_party: str | None
    error: str
