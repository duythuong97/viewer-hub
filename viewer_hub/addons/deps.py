"""Addons that read each other (``uses`` → ``exports``): is everything installed compatible (docs/plans/addon-interop.md §4).

Pure functions over checked manifests (manifest.Addon), no Flask and no files, so the same rules serve:

    check_install(new, installed)   what installing ``new`` (a zip) does to it and to the addons around it
    check_remove(addon_id, ...)     who loses a dependency when an addon is removed
    statuses(installed)             ok / degraded / broken of every installed addon (Settings, the addon's page)
    call_problem(...)               the same rules for one call at run time (state can change after install)
    install_order(addons)           providers before the addons that use them (default addons at start)

An Issue is ``block`` (cannot install), ``warn`` (the admin must accept it, by its ``key``) or ``note`` (shown).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable

from viewer_hub.addons import semver
from viewer_hub.addons.contract import Change, breaking, compare_export, compare_exports
from viewer_hub.addons.manifest import Addon, Use

BLOCK, WARN, NOTE = "block", "warn", "note"
OK, DEGRADED, BROKEN = "ok", "degraded", "broken"
MAX_CHANGES = 6   # changes named in one message


@dataclass(frozen=True)
class Issue:
    level: str
    code: str        # missing, version, export, contract, premium, cycle, breaking, dependent, downgrade, unused
    message: str     # Vietnamese, for the admin
    addon: str = ""  # the other addon it is about
    key: str = ""    # stable id the admin accepts a warning by

    def public(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "addon": self.addon, "key": self.key}


def _changes_text(changes: list[Change]) -> str:
    shown = "; ".join(str(c) for c in changes[:MAX_CHANGES])
    return shown + (f"; … {len(changes) - MAX_CHANGES} thay đổi nữa" if len(changes) > MAX_CHANGES else "")


def _name(addon: Addon | None, addon_id: str) -> str:
    return f"{addon.name} ({addon_id})" if addon else addon_id


def use_problems(user: Addon, use: Use, provider: Addon | None, premium_ok: Callable[[str], bool]) -> list[Issue]:
    """What is wrong between ``user`` and the addon it ``use``s, as installed now (U3–U7, also P3–P5 from the other
    side). Level: WARN for a required use, NOTE for an optional one (premium is always a NOTE)."""
    level = NOTE if use.optional else WARN
    who = _name(provider, use.id)
    if provider is None:
        return [Issue(level, "missing", f"{user.name} cần {use.id} {use.range}, chưa cài: "
                                         f"{'tính năng dùng ' + use.id + ' tắt' if use.optional else 'phần dùng ' + use.id + ' sẽ lỗi'}"
                                         " cho tới khi cài", use.id, f"missing:{user.id}:{use.id}")]
    issues: list[Issue] = []
    try:
        fits = use.range.satisfied_by(provider.version)
    except semver.VersionError:
        fits = False
    if not fits:
        issues.append(Issue(level, "version", f"{user.name} cần {who} {use.range}, đang có {provider.version}",
                            use.id, f"version:{user.id}:{use.id}:{provider.version}"))
    exports = {e.name: e for e in provider.exports}
    gone = [name for name in use.exports if name not in exports]
    if gone:
        issues.append(Issue(level, "export", f"{user.name} gọi {', '.join(gone)} của {who}, bản {provider.version} "
                                             "không có", use.id, f"export:{user.id}:{use.id}:{provider.version}"))
    changes: list[Change] = []
    for name, schemas in use.built.items():
        if name in exports:
            changes += breaking(compare_export(name, schemas, exports[name]))
    if changes:
        issues.append(Issue(level, "contract", f"{user.name} được build với {use.id} {use.built_version}; {who} "
                                               f"{provider.version} khác ở chỗ {user.name} dựa vào: {_changes_text(changes)}",
                            use.id, f"contract:{user.id}:{use.id}:{provider.version}"))
    if provider.premium and not premium_ok(provider.premium):
        issues.append(Issue(NOTE, "premium", f"{who} đang khoá premium: {user.name} chỉ đọc được khi mở khoá", use.id))
    return issues


def _cycle(new: Addon, installed: dict[str, Addon]) -> list[str]:
    """A path new → … → new through ``uses`` (empty when there is none)."""
    graph = {a.id: [u.id for u in a.uses] for a in installed.values() if a.id != new.id}
    graph[new.id] = [u.id for u in new.uses]
    stack: list[tuple[str, list[str]]] = [(new.id, [new.id])]
    seen: set[str] = set()
    while stack:
        node, path = stack.pop()
        for nxt in graph.get(node, []):
            if nxt == new.id:
                return path + [nxt]
            if nxt not in seen:
                seen.add(nxt)
                stack.append((nxt, path + [nxt]))
    return []


def check_install(new: Addon, installed: dict[str, Addon], premium_ok: Callable[[str], bool] = lambda _p: True
                  ) -> list[Issue]:
    """Issues of installing ``new`` over what is ``installed`` ({id: Addon}, may hold the old copy of ``new``)."""
    issues: list[Issue] = []
    old = installed.get(new.id)
    others = {i: a for i, a in installed.items() if i != new.id}
    # a) new as a user of others (U3–U8)
    for use in new.uses:
        issues += use_problems(new, use, others.get(use.id), premium_ok)
    cycle = _cycle(new, others)
    if cycle:
        issues.append(Issue(BLOCK, "cycle", "vòng phụ thuộc " + " → ".join(cycle) + ": hai addon gọi nhau dễ treo cả "
                                            "hai; bỏ một chiều trong uses", cycle[1]))
    # b) new as a provider (P2–P7)
    if old is not None:
        try:
            downgrade = semver.parse(new.version) < semver.parse(old.version)
            same_major = semver.parse(new.version).major == semver.parse(old.version).major
        except semver.VersionError:
            downgrade, same_major = False, False
        own = breaking(compare_exports(old.exports, new.exports))
        if own and same_major and not downgrade:
            issues.append(Issue(BLOCK, "breaking", f"{new.name} {new.version} đổi export phá vỡ addon khác mà không tăng "
                                                   f"major (đang cài {old.version}): {_changes_text(own)}. Tăng version "
                                                   f"lên {semver.parse(old.version).major + 1}.0.0", new.id))
        if downgrade:
            issues.append(Issue(WARN, "downgrade", f"hạ {new.name} từ {old.version} xuống {new.version}", new.id,
                                f"downgrade:{new.id}:{old.version}:{new.version}"))
    for user in sorted(others.values(), key=lambda a: a.id):
        for use in user.uses:
            if use.id != new.id:
                continue
            for issue in use_problems(user, use, new, premium_ok):
                if issue.code == "premium":
                    continue
                # Installed and working now, broken after: always the admin's choice (a WARN), even for optional.
                before = use_problems(user, use, old, premium_ok) if old is not None else None
                if before is not None and any(b.code == issue.code for b in before):
                    continue  # already so before this install: not this zip's doing
                issues.append(Issue(WARN, "dependent", f"sau khi cài {new.name} {new.version}: {issue.message}",
                                    user.id, f"dependent:{user.id}:{issue.code}:{new.version}"))
    if old is not None:
        used = {name for a in others.values() for u in a.uses if u.id == new.id for name in u.exports}
        dropped = [e.name for e in old.exports if e.name not in {x.name for x in new.exports} and e.name not in used]
        if dropped:
            issues.append(Issue(NOTE, "unused", f"bỏ export {', '.join(dropped)} (không addon nào đang dùng)", new.id))
    return issues


def check_remove(addon_id: str, installed: dict[str, Addon]) -> list[Issue]:
    """Addons that use ``addon_id`` (O1): a required use is a WARN, an optional one a NOTE."""
    issues = []
    for user in sorted(installed.values(), key=lambda a: a.id):
        for use in user.uses:
            if use.id == addon_id:
                level = NOTE if use.optional else WARN
                issues.append(Issue(level, "dependent", f"{user.name} dùng {addon_id} ({', '.join(use.exports)}): "
                                                        f"{'tính năng đó sẽ tắt' if use.optional else 'phần đó sẽ lỗi'}",
                                    user.id, f"remove:{user.id}:{addon_id}"))
    return issues


@dataclass
class Status:
    state: str = OK
    reasons: list[str] = field(default_factory=list)
    uses: list[dict] = field(default_factory=list)      # [{id, name, version, optional, exports, ok, reasons}]
    used_by: list[dict] = field(default_factory=list)   # [{id, name, exports}]

    def public(self) -> dict:
        return {"state": self.state, "reasons": self.reasons, "uses": self.uses, "usedBy": self.used_by}


def statuses(installed: dict[str, Addon], premium_ok: Callable[[str], bool] = lambda _p: True) -> dict[str, Status]:
    out = {addon_id: Status() for addon_id in installed}
    for user in installed.values():
        status = out[user.id]
        for use in user.uses:
            provider = installed.get(use.id)
            problems = [p for p in use_problems(user, use, provider, premium_ok)]
            hard = [p for p in problems if p.level == WARN]
            status.uses.append({"id": use.id, "name": provider.name if provider else use.id,
                                "version": provider.version if provider else "", "range": str(use.range),
                                "optional": use.optional, "exports": list(use.exports),
                                "ok": not problems, "reasons": [p.message for p in problems]})
            status.reasons += [p.message for p in problems if p.code != "premium"]
            if hard:
                status.state = BROKEN
            elif problems and status.state == OK and any(p.code != "premium" for p in problems):
                status.state = DEGRADED
            if provider is not None:
                out[provider.id].used_by.append({"id": user.id, "name": user.name, "exports": list(use.exports)})
    return out


def call_problem(caller: Addon, target_id: str, export: str, installed: dict[str, Addon],
                 premium_ok: Callable[[str], bool]) -> tuple[str, str, int] | None:
    """(code, message, HTTP status) when ``caller`` may not call ``target_id``.``export`` now, else None."""
    use = next((u for u in caller.uses if u.id == target_id), None)
    if use is None or export not in use.exports:
        return ("export_unknown", f"{caller.id} chưa khai {target_id}.{export} trong uses của addon.json", 403)
    target = installed.get(target_id)
    if target is None:
        return ("dependency_missing", f"chưa cài addon {target_id}", 424)
    if target.premium and not premium_ok(target.premium):
        return ("dependency_missing", f"chưa cài addon {target_id}", 424)  # a locked addon does not exist
    if not use.range.satisfied_by(target.version):
        return ("dependency_incompatible", f"cần {target_id} {use.range}, đang có {target.version}", 424)
    exported = next((e for e in target.exports if e.name == export), None)
    if exported is None:
        return ("export_unknown", f"{target_id} {target.version} không có export {export}", 424)
    if export in use.built:
        changes = breaking(compare_export(export, use.built[export], exported))
        if changes:
            return ("dependency_incompatible", f"{target_id}.{export} đã đổi: {_changes_text(changes)}", 424)
    return None


def install_order(addons: Iterable[Addon]) -> list[Addon]:
    """Providers first (a stable topological order by id); addons in a cycle keep their id order at the end."""
    pending = {a.id: a for a in addons}
    done: list[Addon] = []
    placed: set[str] = set()
    while pending:
        ready = sorted(i for i, a in pending.items() if all(u.id in placed or u.id not in pending for u in a.uses))
        if not ready:
            ready = sorted(pending)
        for addon_id in ready:
            done.append(pending.pop(addon_id))
            placed.add(addon_id)
    return done


def blocking(issues: list[Issue], accepted: Iterable[str] = ()) -> list[Issue]:
    """What stops an install: every BLOCK, and every WARN whose key was not accepted."""
    accepted = set(accepted)
    return [i for i in issues if i.level == BLOCK or (i.level == WARN and i.key not in accepted)]
