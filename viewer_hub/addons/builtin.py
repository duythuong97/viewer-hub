"""Builtin modules as providers of ``exports`` (docs/addons.md §3.2, docs/solutions/codemap-redesign-solution.md §5.3).

A builtin module declares ``exports=Exports(contract=<json>, call=<fn>)`` in its ``Module(...)``: the contract file has
the addon.json ``exports`` format (contract.py checks it the same way). To the dependency rules (deps.py) the module is
one more provider, shaped like a manifest.Addon:

* its id is the module key, its version the Hub's version, it uses nothing;
* it is always present: a builtin module is never premium (app/modules.py), so it cannot be locked;
* the Hub calls it in-process (routes.py call): params and the reply are still checked against the contract and the
  call is recorded in Giám sát, like a call to an addon.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import cache
from typing import Callable

from viewer_hub.addons.contract import ContractError, Export, parse_exports


@dataclass(frozen=True)
class BuiltinProvider:
    id: str
    name: str
    version: str
    summary: str
    exports: tuple[Export, ...]
    call: Callable = field(hash=False, compare=False)
    premium: str | None = None
    uses: tuple = ()
    builtin: bool = True


def load(module) -> BuiltinProvider:
    """The provider of one builtin module that declares ``exports`` (ContractError: its contract file is wrong)."""
    from viewer_hub import __version__

    try:
        raw = json.loads(module.exports.contract.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ContractError(f"{module.key}: không đọc được {module.exports.contract.name}: {exc}") from exc
    return BuiltinProvider(module.key, module.label, __version__, module.summary, parse_exports(raw), module.exports.call)


@cache
def providers() -> dict[str, BuiltinProvider]:
    """{module key: provider} of every builtin module with ``exports`` (read once: they ship with the Hub)."""
    from viewer_hub.app.modules import all_modules

    return {module.key: load(module) for module in all_modules() if module.exports is not None}


def with_builtin(installed: dict) -> dict:
    """``installed`` addons plus the builtin providers (an addon id never takes a module key: install.reserved_ids)."""
    return {**providers(), **installed}
