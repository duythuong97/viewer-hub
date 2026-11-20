"""Semantic versions and the small range syntax of ``uses`` / ``requires`` in addon.json (docs/addons.md §3.2).

    1.2.3 / 1.2.3-beta.1      a version (manifest.VERSION_RE also allows a fourth number: 1.2.3.4, compared as a
                              prerelease-free build part, so 1.2.3.4 > 1.2.3)
    ^1.2.3                    >=1.2.3 <2.0.0   (^0.2.3: <0.3.0, ^0.0.3: <0.0.4)
    ~1.2.3                    >=1.2.3 <1.3.0
    >=1.2.0 <2                comparators (>, >=, <, <=, =), all must hold
    ^1.2 || ^2.0              either side
    1.2.3                     exactly that version;  *  any version

Partial versions (``1``, ``1.2``) fill the missing parts with 0, except after ``^`` / ``~`` where they set the upper
bound like npm (``~1`` = >=1.0.0 <2.0.0). A prerelease (1.3.0-beta) only satisfies a range whose comparator names a
prerelease of the same x.y.z, as in npm: ``^1.2.0`` does not pick up 1.3.0-beta by accident.

Standard library only; no third-party semver package (docs/GUIDELINE.md §5.3).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Same shapes as manifest.VERSION_RE: 1.2.3, 1.2.3.4, 1.2.3-beta.1, 1.2.3.beta (a dot before a prerelease too).
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:[.-]([0-9A-Za-z.-]+))?$")
_PARTIAL = re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$")
_COMPARATOR = re.compile(r"^(>=|<=|>|<|=|\^|~)?\s*(.+)$")
MAX_RANGE = 200


class VersionError(ValueError):
    """Not a version, or not a range this module understands."""


@dataclass(frozen=True, order=False)
class Version:
    major: int
    minor: int
    patch: int
    build: int = 0                      # the fourth number manifest.VERSION_RE allows
    pre: tuple[int | str, ...] = ()     # prerelease identifiers; () = a release

    @property
    def triple(self) -> tuple[int, int, int]:
        return self.major, self.minor, self.patch

    def key(self) -> tuple:
        # A release sorts after its prereleases; numeric identifiers before alphanumeric ones (semver §11).
        pre = tuple((0, part, "") if isinstance(part, int) else (1, 0, part) for part in self.pre)
        return (self.major, self.minor, self.patch, self.build, 1 if not self.pre else 0, pre)

    def __lt__(self, other: "Version") -> bool:
        return self.key() < other.key()

    def __le__(self, other: "Version") -> bool:
        return self.key() <= other.key()

    def __gt__(self, other: "Version") -> bool:
        return self.key() > other.key()

    def __ge__(self, other: "Version") -> bool:
        return self.key() >= other.key()

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}" + (f".{self.build}" if self.build else "")
        return text + ("-" + ".".join(str(p) for p in self.pre) if self.pre else "")


def _pre(text: str | None) -> tuple[int | str, ...]:
    if not text:
        return ()
    parts = text.split(".")
    if any(not part for part in parts):
        raise VersionError(f"prerelease không hợp lệ: {text}")
    return tuple(int(part) if part.isdigit() else part for part in parts)


def parse(text: str) -> Version:
    match = _VERSION.match(text.strip()) if isinstance(text, str) else None
    if not match:
        raise VersionError(f"không phải version dạng 1.2.3: {text!r}")
    major, minor, patch, build, pre = match.groups()
    return Version(int(major), int(minor), int(patch), int(build or 0), _pre(pre))


@dataclass(frozen=True)
class _Bound:
    op: str             # one of > >= < <= =
    version: Version

    def holds(self, version: Version) -> bool:
        a, b = version.key(), self.version.key()
        return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b, "=": a == b}[self.op]


def _partial(text: str) -> tuple[Version, int]:
    """(version with missing parts as 0, how many numbers were given)."""
    match = _PARTIAL.match(text)
    if not match:
        raise VersionError(f"không phải version: {text!r}")
    major, minor, patch, pre = match.groups()
    given = 1 + (minor is not None) + (patch is not None)
    if pre and given < 3:
        raise VersionError(f"prerelease cần đủ x.y.z: {text!r}")
    return Version(int(major), int(minor or 0), int(patch or 0), 0, _pre(pre)), given


def _comparator(token: str) -> list[_Bound]:
    match = _COMPARATOR.match(token)
    if not match:
        raise VersionError(f"không hiểu {token!r}")
    op, rest = match.group(1) or "", match.group(2)
    if _VERSION.match(rest) and op in ("", "="):
        return [_Bound("=", parse(rest))]  # 1.2.3.4 exact (the partial form has no fourth number)
    low, given = _partial(rest)
    if op == "^":
        if low.major or given == 1:
            high = Version(low.major + 1, 0, 0)
        elif low.minor or given == 2:
            high = Version(0, low.minor + 1, 0)
        else:
            high = Version(0, 0, low.patch + 1)
        return [_Bound(">=", low), _Bound("<", Version(*high.triple, 0, (0,)))]
    if op == "~":
        high = Version(low.major + 1, 0, 0) if given == 1 else Version(low.major, low.minor + 1, 0)
        return [_Bound(">=", low), _Bound("<", Version(*high.triple, 0, (0,)))]
    if op in ("", "="):
        if given == 3:
            return [_Bound("=", low)]
        high = Version(low.major + 1, 0, 0) if given == 1 else Version(low.major, low.minor + 1, 0)
        return [_Bound(">=", low), _Bound("<", Version(*high.triple, 0, (0,)))]  # 1.2 = 1.2.x
    return [_Bound(op, low)]


@dataclass(frozen=True)
class Range:
    text: str
    alternatives: tuple[tuple[_Bound, ...], ...]   # OR of ANDs; () inside = any version

    def satisfied_by(self, version: Version | str) -> bool:
        if isinstance(version, str):
            version = parse(version)
        for bounds in self.alternatives:
            if not all(bound.holds(version) for bound in bounds):
                continue
            # npm: a prerelease only counts when this set names a prerelease of the same x.y.z (the upper bound
            # x.y.z-0 that ^ / ~ add is not a real prerelease the author named).
            if version.pre and not any(b.version.pre and b.version.pre != (0,) and b.version.triple == version.triple
                                       for b in bounds):
                continue
            return True
        return False

    def __str__(self) -> str:
        return self.text


def parse_range(text: str) -> Range:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_RANGE:
        raise VersionError("khoảng version phải là chuỗi (vd. ^1.2.0)")
    alternatives = []
    for part in text.split("||"):
        part = part.strip()
        if not part:
            raise VersionError(f"khoảng version không hợp lệ: {text!r}")
        if part == "*":
            alternatives.append(())
            continue
        # ">= 1.2" is one comparator: glue an operator to the version after it.
        tokens = re.sub(r"(>=|<=|>|<|=|\^|~)\s+", r"\1", part).split()
        bounds: list[_Bound] = []
        for token in tokens:
            bounds += _comparator(token)
        alternatives.append(tuple(bounds))
    return Range(text.strip(), tuple(alternatives))


def satisfies(version: str, range_text: str) -> bool:
    return parse_range(range_text).satisfied_by(parse(version))
