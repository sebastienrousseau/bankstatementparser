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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Plugin and dynamic entrypoint discovery for bankstatementparser.

Allows companion loader packages (e.g. ``bankstatementparser-loader-bai2``,
``bankstatementparser-loader-mt942``) and writer packages (e.g.
``bankstatementparser-writer-xlsx``) to be registered dynamically via Python
entry points without hardcoding them into the core package.
"""

from __future__ import annotations

import importlib.metadata
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .base_parser import BankStatementParser

logger = logging.getLogger(__name__)

LOADER_ENTRYPOINT_GROUP = "bankstatementparser.loaders"
WRITER_ENTRYPOINT_GROUP = "bankstatementparser.writers"

_MANUAL_LOADERS: dict[str, type[BankStatementParser]] = {}
_MANUAL_WRITERS: dict[str, Callable[..., Any]] = {}


def register_loader(name: str, parser_cls: type[BankStatementParser]) -> None:
    """Manually register a bank statement parser class.

    Args:
        name: The format identifier (e.g. 'bai2', 'mt942').
        parser_cls: The parser class inheriting from ``BankStatementParser``.
    """
    _MANUAL_LOADERS[name.lower()] = parser_cls


def unregister_loader(name: str) -> None:
    """Unregister a manually registered parser class.

    Args:
        name: The format identifier to remove.
    """
    _MANUAL_LOADERS.pop(name.lower(), None)


def register_writer(name: str, writer_fn: Callable[..., Any]) -> None:
    """Manually register an export writer callable.

    Args:
        name: The writer identifier (e.g. 'xlsx').
        writer_fn: The writer function.
    """
    _MANUAL_WRITERS[name.lower()] = writer_fn


def unregister_writer(name: str) -> None:
    """Unregister a manually registered writer callable.

    Args:
        name: The writer identifier to remove.
    """
    _MANUAL_WRITERS.pop(name.lower(), None)


def discover_loaders() -> dict[str, type[BankStatementParser]]:
    """Discover statement loader plugins via entry points.

    Returns:
        Mapping of format name to parser class.
    """
    discovered: dict[str, type[BankStatementParser]] = {}
    try:
        try:
            loader_eps: Any = importlib.metadata.entry_points(
                group=LOADER_ENTRYPOINT_GROUP
            )
        except TypeError:
            eps_any: Any = importlib.metadata.entry_points()
            loader_eps = (
                eps_any.select(group=LOADER_ENTRYPOINT_GROUP)
                if hasattr(eps_any, "select")
                else eps_any.get(LOADER_ENTRYPOINT_GROUP, [])
            )
        for ep in loader_eps:
            try:
                loaded = ep.load()
                discovered[ep.name.lower()] = loaded
            except Exception as exc:
                logger.warning(
                    "Failed to load parser plugin %r: %s", ep.name, exc
                )
    except Exception as exc:
        logger.debug("Failed to discover loader entry points: %s", exc)

    return discovered


def discover_writers() -> dict[str, Callable[..., Any]]:
    """Discover export writer plugins via entry points.

    Returns:
        Mapping of format name to writer callable.
    """
    discovered: dict[str, Callable[..., Any]] = {}
    try:
        try:
            writer_eps: Any = importlib.metadata.entry_points(
                group=WRITER_ENTRYPOINT_GROUP
            )
        except TypeError:
            eps_any: Any = importlib.metadata.entry_points()
            writer_eps = (
                eps_any.select(group=WRITER_ENTRYPOINT_GROUP)
                if hasattr(eps_any, "select")
                else eps_any.get(WRITER_ENTRYPOINT_GROUP, [])
            )
        for ep in writer_eps:
            try:
                loaded = ep.load()
                discovered[ep.name.lower()] = loaded
            except Exception as exc:
                logger.warning(
                    "Failed to load writer plugin %r: %s", ep.name, exc
                )
    except Exception as exc:
        logger.debug("Failed to discover writer entry points: %s", exc)

    return discovered


def get_registered_loaders() -> dict[str, type[BankStatementParser]]:
    """Return all available loader plugins (discovered + manually registered).

    Returns:
        Dictionary mapping format identifiers to parser classes.
    """
    loaders = discover_loaders()
    loaders.update(_MANUAL_LOADERS)
    return loaders


def get_registered_writers() -> dict[str, Callable[..., Any]]:
    """Return all available writer plugins (discovered + manually registered).

    Returns:
        Dictionary mapping format identifiers to writer callables.
    """
    writers = discover_writers()
    writers.update(_MANUAL_WRITERS)
    return writers
