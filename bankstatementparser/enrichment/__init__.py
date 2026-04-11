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

"""Optional enrichment layer — categorization and inference helpers.

The enrichment layer is **opinion**, not **data**. The deterministic
core of :mod:`bankstatementparser` deliberately ships zero
inferences: every field on a :class:`~..transaction_models.Transaction`
is a fact extracted from the source statement. Categorization, tax
classification, and similar derived fields are intentionally pushed
into this opt-in module so the trust model of the core stays clean.

Install:

    pip install bankstatementparser[enrichment]

Usage:

    from bankstatementparser.enrichment import (
        Categorizer,
        DEFAULT_CATEGORY_SCHEMA,
    )

    cat = Categorizer()  # uses BSP_HYBRID_ENRICHMENT_MODEL or BSP_HYBRID_MODEL
    enriched = cat.categorize_batch(transactions)
    for et in enriched:
        print(et.transaction.description, "->", et.category)

The categorizer wraps :class:`Transaction` in
:class:`EnrichedTransaction` rather than mutating the underlying
model so audit trails always have access to the original
deterministic fields.
"""

from __future__ import annotations

from .account_mapper import AccountMapper, AccountRule
from .categorizer import (
    DEFAULT_CATEGORY_SCHEMA,
    Categorizer,
    CategorizerError,
    EnrichedTransaction,
)

__all__ = [
    "AccountMapper",
    "AccountRule",
    "DEFAULT_CATEGORY_SCHEMA",
    "Categorizer",
    "CategorizerError",
    "EnrichedTransaction",
]
