"""The per-market rule pack: the interdiction policy as DATA, parsed into frozen types.

The engine has no market branch and no threshold literal in it. Every number a payment is judged
against, the regulator instrument each rule cites, and the score cutoffs that turn a score into
an allow / warn / hold / block verdict all live in a pack (``rulepacks/<market>.yaml``), so a new
market or a changed threshold is a data edit a policy owner reviews, never a code change.

This module is PURE: it parses an already-loaded mapping into frozen dataclasses and validates
it. Reading the YAML file is the loader's job (``app_fraud_interdiction.rulepacks_loader``), which
lives outside ``domain/`` because it depends on a YAML parser and the domain depends on nothing
but the standard library.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .kernel import RiskBand

#: The comparison operators a rule may use, each a pure function of (feature value, threshold).
#: A closed set: a pack naming an operator not here is refused at parse time rather than silently
#: never firing.
_OPS: dict[str, Any] = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
}


@dataclass(frozen=True, slots=True)
class Rule:
    """One deterministic rule: fire when ``feature_key <op> threshold``, adding ``uplift``."""

    code: str
    title: str
    feature_key: str
    op: str
    threshold: float
    uplift: int
    locator: str

    def __post_init__(self) -> None:
        if self.op not in _OPS:
            raise ValueError(f"rule {self.code!r} uses unknown operator {self.op!r}")
        if not self.code.strip():
            raise ValueError("a rule must have a non-empty code")

    def fires(self, value: float) -> bool:
        """Does this rule fire on ``value``? A pure comparison, no I/O and no clock."""
        return bool(_OPS[self.op](value, self.threshold))


@dataclass(frozen=True, slots=True)
class RulePack:
    """A market's whole interdiction policy: rules, score cutoffs and the citing instrument."""

    market: str
    instrument: str
    version: str
    baseline_score: int
    warn_at: int
    hold_at: int
    block_at: int
    medium_band_at: int
    high_band_at: int
    critical_band_at: int
    rules: tuple[Rule, ...]

    def __post_init__(self) -> None:
        if not (self.warn_at <= self.hold_at <= self.block_at):
            raise ValueError(
                f"pack {self.market!r} verdict cutoffs must be non-decreasing: "
                f"warn {self.warn_at} <= hold {self.hold_at} <= block {self.block_at}"
            )
        if not (self.medium_band_at <= self.high_band_at <= self.critical_band_at):
            raise ValueError(f"pack {self.market!r} band cutoffs must be non-decreasing")
        codes = [rule.code for rule in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError(f"pack {self.market!r} has duplicate rule codes")

    def band_for(self, score: int) -> RiskBand:
        """Map a score to its :class:`RiskBand` using the pack's own cutoffs (no engine literal)."""
        if score >= self.critical_band_at:
            return RiskBand.CRITICAL
        if score >= self.high_band_at:
            return RiskBand.HIGH
        if score >= self.medium_band_at:
            return RiskBand.MEDIUM
        return RiskBand.LOW

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RulePack:
        """Parse and validate a pack from an already-loaded mapping. Pure: no file access here."""
        try:
            raw_rules = data["rules"]
            thresholds = data["thresholds"]
            bands = data["bands"]
            rules = tuple(
                Rule(
                    code=str(row["code"]),
                    title=str(row["title"]),
                    feature_key=str(row["feature"]),
                    op=str(row["op"]),
                    threshold=float(row["threshold"]),
                    uplift=int(row["uplift"]),
                    locator=str(row["locator"]),
                )
                for row in raw_rules
            )
            return cls(
                market=str(data["market"]),
                instrument=str(data["instrument"]),
                version=str(data["version"]),
                baseline_score=int(data.get("baseline_score", 0)),
                warn_at=int(thresholds["warn"]),
                hold_at=int(thresholds["hold"]),
                block_at=int(thresholds["block"]),
                medium_band_at=int(bands["medium"]),
                high_band_at=int(bands["high"]),
                critical_band_at=int(bands["critical"]),
                rules=rules,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid rule pack: {exc}") from exc
