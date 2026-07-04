"""Connector packages grouped by source category (spec sections 1-13).

Importing this package dynamically imports every subpackage so that
``@register_source`` runs for each connector. Add a new category package and
it is discovered automatically — no manual import list to maintain
(open-closed).
"""

from __future__ import annotations

import importlib
import pkgutil


def _import_all() -> None:
    for module_info in pkgutil.iter_modules(__path__, __name__ + "."):
        importlib.import_module(module_info.name)


_import_all()
