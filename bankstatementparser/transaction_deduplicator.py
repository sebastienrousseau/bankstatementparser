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

"""Deterministic transaction deduplication utilities."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from .transaction_models import Transaction


def _days_between(left: date | None, right: date | None) -> int | None:
    """Return the absolute day gap between two dates, or None."""
    if left is None or right is None:
        return None
    return abs((left - right).days)


def _description_similarity(left: Transaction, right: Transaction) -> float:
    """Return the 0.0-1.0 similarity of two normalized descriptions."""
    if not left.normalized_description or not right.normalized_description:
        return 0.0
    return SequenceMatcher(
        None, left.normalized_description, right.normalized_description
    ).ratio()


class ExactDuplicateGroup(BaseModel):
    """Transactions that collide on the deterministic primary hash."""

    model_config = ConfigDict(frozen=True)

    primary_hash: str
    transactions: list[Transaction]


class MatchGroup(BaseModel):
    """A set of transactions requiring operator review."""

    model_config = ConfigDict(frozen=True)

    transactions: list[Transaction]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    tier: str


class DeduplicationResult(BaseModel):
    """Explainable deduplication output."""

    model_config = ConfigDict(frozen=True)

    unique_transactions: list[Transaction]
    exact_duplicates: list[ExactDuplicateGroup]
    suspected_matches: list[MatchGroup]


@dataclass(frozen=True)
class _Candidate:
    """A transaction paired with its source index and primary hash."""

    index: int
    transaction: Transaction
    primary_hash: str


class Deduplicator:
    """Deduplicate bank transactions with deterministic match tiers."""

    def __init__(
        self,
        *,
        value_date_window_days: int = 3,
        description_similarity_threshold: float = 0.9,
    ) -> None:
        """Configure the fuzzy-match tier.

        Args:
            value_date_window_days: Maximum day gap between value
                dates for two transactions to be suspected matches.
            description_similarity_threshold: Minimum normalized
                description similarity (0 to 1) for a suspected
                match.
        """
        self.value_date_window_days = value_date_window_days
        self.description_similarity_threshold = (
            description_similarity_threshold
        )

    def primary_hash(self, transaction: Transaction) -> str:
        """Return the stable primary hash for hard identity matching."""
        material = "|".join(
            [
                transaction.account_id or "",
                transaction.currency or "",
                transaction.amount_key(),
                transaction.booking_date.isoformat()
                if transaction.booking_date is not None
                else "",
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def normalize_transactions(
        self,
        transactions: Iterable[Transaction | dict[str, object]],
        *,
        source: str | None = None,
    ) -> list[Transaction]:
        """Normalize transaction inputs into deterministic models."""
        normalized: list[Transaction] = []
        for index, transaction in enumerate(transactions):
            if isinstance(transaction, Transaction):
                normalized.append(
                    transaction.model_copy(
                        update={
                            "source": transaction.source or source,
                            "source_index": (
                                transaction.source_index
                                if transaction.source_index is not None
                                else index
                            ),
                        }
                    )
                )
            else:
                normalized.append(
                    Transaction.from_record(
                        dict(transaction),
                        source=source,
                        source_index=index,
                    )
                )
        return normalized

    def dedupe_by_hash(
        self,
        transactions: Iterable[Transaction | dict[str, object]],
        *,
        seen_hashes: set[str] | None = None,
    ) -> tuple[list[Transaction], list[str]]:
        """Idempotent set-based dedup using ``Transaction.transaction_hash``.

        Designed for incremental ingestion (e.g. syncing to Google
        Sheets / a database) where each row carries its own immutable
        fingerprint. Unlike :meth:`deduplicate`, this performs no fuzzy
        matching — it is a strict identity filter.

        Stored keys are occurrence-counted (``<hash>:<n>``): the nth
        occurrence of a hash in a batch matches the nth persisted key.
        Re-ingesting the same batch is therefore idempotent, while
        genuine repeats within one statement (two identical same-day
        purchases) are not silently dropped.

        Args:
            transactions: Items to ingest.
            seen_hashes: Occurrence-counted keys already persisted
                upstream by a previous call. New keys from this batch
                are added in-place.

        Returns:
            Tuple of (new transactions, list of skipped duplicate
            hashes from this batch).
        """
        if seen_hashes is None:
            seen_hashes = set()
        normalized = self.normalize_transactions(transactions)
        unique: list[Transaction] = []
        skipped: list[str] = []
        occurrences: dict[str, int] = defaultdict(int)
        for tx in normalized:
            digest = tx.transaction_hash
            key = f"{digest}:{occurrences[digest]}"
            occurrences[digest] += 1
            if key in seen_hashes:
                skipped.append(digest)
                continue
            seen_hashes.add(key)
            unique.append(tx)
        return unique, skipped

    def from_dataframe(
        self, df: pd.DataFrame, *, source: str | None = None
    ) -> list[Transaction]:
        """Normalize parser DataFrame output into transaction models."""
        return self.normalize_transactions(
            df.to_dict("records"), source=source
        )

    def deduplicate(
        self, transactions: Iterable[Transaction | dict[str, object]]
    ) -> DeduplicationResult:
        """Deduplicate transactions into unique, exact, and suspected sets."""
        normalized = self.normalize_transactions(transactions)
        candidates = [
            _Candidate(
                index=index,
                transaction=transaction,
                primary_hash=self.primary_hash(transaction),
            )
            for index, transaction in enumerate(normalized)
        ]

        exact_groups = self._find_exact_duplicates(candidates)
        exact_indices = {
            candidate.index
            for bucket in self._candidate_groups_by_primary(
                candidates
            ).values()
            if len(bucket) > 1
            for candidate in bucket
        }
        suspected_groups, suspected_indices = self._find_suspected_matches(
            candidates,
            excluded_indices=exact_indices,
        )

        unique_transactions = [
            candidate.transaction
            for candidate in candidates
            if candidate.index not in exact_indices | suspected_indices
        ]

        return DeduplicationResult(
            unique_transactions=unique_transactions,
            exact_duplicates=exact_groups,
            suspected_matches=suspected_groups,
        )

    def _candidate_groups_by_primary(
        self, candidates: list[_Candidate]
    ) -> dict[str, list[_Candidate]]:
        """Group candidates by their primary hash."""
        groups: dict[str, list[_Candidate]] = defaultdict(list)
        for candidate in candidates:
            groups[candidate.primary_hash].append(candidate)
        return groups

    def _find_exact_duplicates(
        self, candidates: list[_Candidate]
    ) -> list[ExactDuplicateGroup]:
        """Return groups of candidates sharing a primary hash."""
        groups = self._candidate_groups_by_primary(candidates)
        exact_groups = []
        for primary_hash, bucket in sorted(groups.items()):
            if len(bucket) < 2:
                continue
            transactions = sorted(
                (candidate.transaction for candidate in bucket),
                key=lambda item: (
                    item.source_index or -1,
                    item.reference or "",
                ),
            )
            exact_groups.append(
                ExactDuplicateGroup(
                    primary_hash=primary_hash,
                    transactions=transactions,
                )
            )
        return exact_groups

    def _find_suspected_matches(
        self,
        candidates: list[_Candidate],
        *,
        excluded_indices: set[int],
    ) -> tuple[list[MatchGroup], set[int]]:
        """Find probable and temporal match groups for operator review."""
        probable_groups, probable_indices = self._find_probable_matches(
            candidates
        )
        temporal_groups, temporal_indices = self._find_temporal_matches(
            [
                candidate
                for candidate in candidates
                if candidate.index not in excluded_indices | probable_indices
            ]
        )
        return (
            probable_groups + temporal_groups,
            probable_indices | temporal_indices,
        )

    def _find_probable_matches(
        self, candidates: list[_Candidate]
    ) -> tuple[list[MatchGroup], set[int]]:
        """Match candidates by hash collision and description similarity."""
        groups = []
        matched_indices: set[int] = set()
        for bucket in self._candidate_groups_by_primary(candidates).values():
            if len(bucket) < 2:
                continue
            similarities = []
            for left_index, left in enumerate(bucket):
                for right in bucket[left_index + 1 :]:
                    similarity = _description_similarity(
                        left.transaction, right.transaction
                    )
                    if (
                        similarity >= self.description_similarity_threshold
                        and left.transaction.normalized_description
                        != right.transaction.normalized_description
                    ):
                        similarities.append(similarity)

            if not similarities:
                continue

            matched_indices.update(candidate.index for candidate in bucket)
            groups.append(
                MatchGroup(
                    transactions=sorted(
                        (candidate.transaction for candidate in bucket),
                        key=lambda item: (
                            item.source_index or -1,
                            item.reference or "",
                        ),
                    ),
                    reason=(
                        "Primary hash collision with description similarity "
                        f"{max(similarities):.2f}"
                    ),
                    confidence=min(0.99, max(similarities) + 0.05),
                    tier="probable",
                )
            )
        return groups, matched_indices

    def _find_temporal_matches(
        self, candidates: list[_Candidate]
    ) -> tuple[list[MatchGroup], set[int]]:
        """Match candidates with equal amounts but shifted value dates."""
        buckets: dict[tuple[str, str, str], list[_Candidate]] = defaultdict(
            list
        )
        for candidate in candidates:
            transaction = candidate.transaction
            buckets[
                (
                    transaction.account_id or "",
                    transaction.currency or "",
                    transaction.amount_key(),
                )
            ].append(candidate)

        groups = []
        matched_indices: set[int] = set()

        def _emit(
            component: list[_Candidate],
            similarities: list[float],
        ) -> None:
            """Record a matched component as a temporal match group."""
            matched_indices.update(candidate.index for candidate in component)
            groups.append(self._temporal_group(component, similarities))

        for bucket in buckets.values():
            if len(bucket) < 2:
                continue

            bucket = sorted(
                bucket,
                key=lambda item: (
                    item.transaction.value_date or date.min,
                    item.index,
                ),
            )
            component: list[_Candidate] = [bucket[0]]
            component_similarities: list[float] = []
            for candidate in bucket[1:]:
                prev = component[-1]
                day_delta = _days_between(
                    prev.transaction.value_date,
                    candidate.transaction.value_date,
                )
                if (
                    day_delta is not None
                    and day_delta <= self.value_date_window_days
                    and prev.primary_hash != candidate.primary_hash
                ):
                    component.append(candidate)
                    component_similarities.append(
                        _description_similarity(
                            prev.transaction, candidate.transaction
                        )
                    )
                    continue

                if len(component) > 1:
                    _emit(component, component_similarities)
                component = [candidate]
                component_similarities = []

            if len(component) > 1:
                _emit(component, component_similarities)

        return groups, matched_indices

    def _temporal_group(
        self,
        component: list[_Candidate],
        similarities: list[float],
    ) -> MatchGroup:
        """Build a temporal MatchGroup with a confidence and reason."""
        max_delta = (
            _days_between(
                component[0].transaction.value_date,
                component[-1].transaction.value_date,
            )
            or 0
        )
        max_similarity = max(similarities) if similarities else 0.0
        confidence = min(0.95, 0.75 + (max_similarity * 0.2))
        reason = f"Value date shift within {max_delta} day window"
        if max_similarity > 0:
            reason += f"; description similarity {max_similarity:.2f}"

        return MatchGroup(
            transactions=[
                candidate.transaction
                for candidate in sorted(component, key=lambda item: item.index)
            ],
            reason=reason,
            confidence=confidence,
            tier="suspected",
        )
