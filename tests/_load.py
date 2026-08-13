"""Load an ezviz_hg2 submodule by file path, without importing the package.

The package's own ``__init__.py`` pulls in Home Assistant, and adding the
integration directory to ``sys.path`` would shadow stdlib modules (it has
its own ``select.py`` platform file). Loading modules individually by path
keeps dependency-free modules testable in isolation.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "ezviz_hg2"


def load(module_name: str) -> ModuleType:
    """Import ``custom_components/ezviz_hg2/<module_name>.py`` standalone."""
    qualified_name = f"ezviz_hg2_{module_name}"
    path = _PACKAGE_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(qualified_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations via sys.modules[cls.__module__], so
    # the module must be registered before exec_module runs its body.
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module
