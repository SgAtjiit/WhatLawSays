"""Re-deriving a procurement finding from the data it claims to rest on.

`verify_quotes` in `red_flag_rules.py` proves a contract finding quotes text that
is really in the document. This module is the same guarantee for findings about
structured data, and it is deliberately held to the same standard rather than a
softer one.

What makes quote grounding work is three properties, and each has an analogue
here:

* *The model never supplies the offsets.* No `field_path` here is written
  freehand either -- every path an evidence object carries was emitted by a
  check's declared `reads` tuple, which is code under test.
* *A quote must be found in the text.* A path must resolve to **exactly one**
  node. A path matching two elements is an `AMBIGUOUS` failure, not a first-match,
  for precisely the reason a quote appearing twice cannot be grounded: nothing
  says which one was meant.
* *An unlocatable quote is discarded, not repaired.* Evidence that does not
  re-derive is reported here and dropped by the compiler.

Two places this is stricter than the quote discipline, because structured data
allows it to be:

* A `DERIVED` value is **re-executed**, not trusted. The computation is looked up
  in `COMPUTATIONS`, run again over the verified inputs, and required to produce
  the same quantised Decimal. A bid-integrity statistic that cannot be reproduced
  is discarded exactly like an invented quote. This is why every figure in this
  subsystem is Decimal: the verifier compares for equality, and float arithmetic
  does not reliably give the same answer twice.
* An `ABSENCE` is only evidence where the enclosing collection was declared
  complete. An absence inside a collection the caller never said it supplied can
  support `UNDETERMINED` and nothing else -- never a breach, and equally never a
  pass.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence

from pydantic import BaseModel

from src.schemas.procurement import (
    STAT_EXPONENT,
    AbsenceEvidence,
    CheckStatus,
    Comparator,
    DerivedEvidence,
    DocumentSpanEvidence,
    FieldEvidence,
    ProcurementFinding,
)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
_SEGMENT = re.compile(rf"^(?P<name>{_IDENT})(?:\[(?P<selector>[^\]]*)\])?$")
# The key may itself be a path, so a bid can be selected on the vendor id that
# lives one level down: bids[vendor.vendor_id="V-2"].
_KEYED = re.compile(rf"^(?P<key>{_IDENT}(?:\.{_IDENT})*)\s*=\s*(?P<literal>.+)$")


class Outcome(str, Enum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    BAD_PATH = "BAD_PATH"


@dataclass(frozen=True)
class Resolution:
    outcome: Outcome
    value: Any = None
    detail: str = ""

    @property
    def found(self) -> bool:
        return self.outcome is Outcome.FOUND


def _child(node: Any, name: str) -> Resolution:
    if isinstance(node, BaseModel):
        if name not in type(node).model_fields:
            return Resolution(Outcome.NOT_FOUND, detail=f"{type(node).__name__} has no field {name!r}")
        return Resolution(Outcome.FOUND, getattr(node, name))
    if isinstance(node, dict):
        if name not in node:
            return Resolution(Outcome.NOT_FOUND, detail=f"no key {name!r}")
        return Resolution(Outcome.FOUND, node[name])
    return Resolution(Outcome.NOT_FOUND, detail=f"cannot read {name!r} from {type(node).__name__}")


def _unquote(literal: str) -> str:
    literal = literal.strip()
    if len(literal) >= 2 and literal[0] == literal[-1] and literal[0] in "\"'":
        return literal[1:-1]
    return literal


def _select(collection: Any, selector: str, path: str) -> Resolution:
    if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
        return Resolution(Outcome.NOT_FOUND, detail=f"{path}: not a list")

    if re.fullmatch(r"\d+", selector):
        index = int(selector)
        if index >= len(collection):
            return Resolution(
                Outcome.NOT_FOUND, detail=f"{path}: index {index} beyond {len(collection)} elements"
            )
        return Resolution(Outcome.FOUND, collection[index])

    keyed = _KEYED.match(selector)
    if not keyed:
        return Resolution(Outcome.BAD_PATH, detail=f"{path}: cannot parse selector {selector!r}")

    key, wanted = keyed.group("key"), _unquote(keyed.group("literal"))
    matches = []
    for element in collection:
        got = resolve(element, key)
        if got.found and _canonical(got.value) == _canonical(wanted):
            matches.append(element)

    if not matches:
        return Resolution(Outcome.NOT_FOUND, detail=f"{path}: no element with {key}={wanted!r}")
    if len(matches) > 1:
        # The direct analogue of a quote that appears twice. Taking the first
        # would be inventing a fact about which one the check meant.
        return Resolution(
            Outcome.AMBIGUOUS,
            detail=f"{path}: {len(matches)} elements with {key}={wanted!r}; a path must pick out one",
        )
    return Resolution(Outcome.FOUND, matches[0])


def _split_segments(path: str) -> List[str]:
    """Split on dots that are not inside a selector.

    `bids[vendor.vendor_id="V-2"].total` is three characters away from being two
    segments and a syntax error, and a naive `path.split(".")` makes it the
    latter. Depth counting is enough here because the grammar does not nest
    brackets.
    """
    segments, current, depth = [], [], 0
    for char in path:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == "." and depth == 0:
            segments.append("".join(current))
            current = []
            continue
        current.append(char)
    segments.append("".join(current))
    return segments


def resolve(root: Any, path: str) -> Resolution:
    """Walk a restricted dotted path, e.g. `bids[vendor_id="V-2"].payment_terms_days`."""
    if not path:
        return Resolution(Outcome.BAD_PATH, detail="empty path")

    node: Any = root
    walked: List[str] = []
    for raw in _split_segments(path):
        walked.append(raw)
        here = ".".join(walked)
        segment = _SEGMENT.match(raw.strip())
        if not segment:
            return Resolution(Outcome.BAD_PATH, detail=f"{here}: not a valid path segment")

        step = _child(node, segment.group("name"))
        if not step.found:
            return Resolution(step.outcome, detail=f"{here}: {step.detail}")
        node = step.value

        selector = segment.group("selector")
        if selector is not None:
            picked = _select(node, selector, here)
            if not picked.found:
                return Resolution(picked.outcome, detail=picked.detail)
            node = picked.value

    return Resolution(Outcome.FOUND, node)


# ---------------------------------------------------------------------------
# Canonical comparison
# ---------------------------------------------------------------------------

def _canonical(value: Any) -> Any:
    """Reduce a value to something two sources can be compared on.

    Evidence travels through JSON on its way to storage and back, so the
    `observed` a finding carries has usually been through a serialization round
    trip that the live object has not. Comparing without normalising would fail
    every stored review -- Decimal("45") against "45", an enum against its value,
    a datetime against its ISO string.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return value.normalize()
    if isinstance(value, (int, float)):
        return Decimal(str(value)).normalize()
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_canonical(v) for v in value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, str):
        text = value.strip()
        # A number that has been through JSON is a string now; compare it as the
        # number it is, so Decimal("45.00") and "45" agree.
        try:
            return Decimal(text).normalize()
        except (InvalidOperation, ValueError):
            return text
    return str(value)


def _as_decimal(value: Any) -> Optional[Decimal]:
    canonical = _canonical(value)
    return canonical if isinstance(canonical, Decimal) else None


def apply_comparator(comparator: Comparator, observed: Any, required: Any) -> Optional[bool]:
    """Re-run the comparison a check claims it made.

    `None` means the comparison could not be made at all -- comparing a missing
    number against a threshold, say. That is a verification failure rather than a
    `False`, because a check should never have asserted a relation it could not
    evaluate.
    """
    if comparator is Comparator.PRESENT:
        return observed is not None
    if comparator is Comparator.ABSENT:
        return observed is None

    left, right = _canonical(observed), _canonical(required)

    if comparator is Comparator.EQ:
        return left == right
    if comparator is Comparator.NE:
        return left != right
    if comparator is Comparator.IN:
        return isinstance(right, list) and left in right
    if comparator is Comparator.NOT_IN:
        return isinstance(right, list) and left not in right

    a, b = _as_decimal(observed), _as_decimal(required)
    if a is None or b is None:
        return None
    if comparator is Comparator.LT:
        return a < b
    if comparator is Comparator.LTE:
        return a <= b
    if comparator is Comparator.GT:
        return a > b
    if comparator is Comparator.GTE:
        return a >= b
    return None


# ---------------------------------------------------------------------------
# The computation registry
# ---------------------------------------------------------------------------

def quantise(value: Decimal) -> Decimal:
    return Decimal(value).quantize(STAT_EXPONENT)


def _decimals(values: Sequence[Any]) -> List[Decimal]:
    out = []
    for v in values:
        d = _as_decimal(v)
        if d is None:
            raise ValueError(f"not a number: {v!r}")
        out.append(d)
    return out


def _mean(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    numbers = _decimals(values)
    return quantise(sum(numbers) / Decimal(len(numbers)))


def _coefficient_of_variation(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    """Spread of the bid totals relative to their size.

    Population standard deviation, not sample: these are all the bids there were,
    not a sample drawn from a larger set of bids that might have been submitted.
    """
    numbers = _decimals(values)
    mean = sum(numbers) / Decimal(len(numbers))
    if mean == 0:
        raise ValueError("mean is zero")
    variance = sum((n - mean) ** 2 for n in numbers) / Decimal(len(numbers))
    return quantise(variance.sqrt() / mean)


def _relative_gap(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    numbers = _decimals(values)
    if len(numbers) != 2:
        raise ValueError("relative_gap takes exactly two values")
    low, high = sorted(numbers)
    if low == 0:
        raise ValueError("lower value is zero")
    return quantise((high - low) / low)


def _stdev_of_ratios(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    numbers = sorted(_decimals(values))
    if len(numbers) < 3:
        raise ValueError("need at least three values")
    ratios = []
    for lower, higher in zip(numbers, numbers[1:]):
        if lower == 0:
            raise ValueError("zero bid total")
        ratios.append(higher / lower)
    mean = sum(ratios) / Decimal(len(ratios))
    variance = sum((r - mean) ** 2 for r in ratios) / Decimal(len(ratios))
    return quantise(variance.sqrt())


def _shared_fraction(values: Sequence[Any], params: Dict[str, str]) -> Decimal:
    """Fraction of compared line items priced identically."""
    matched = Decimal(params.get("matched", "0"))
    compared = Decimal(params.get("compared", "0"))
    if compared == 0:
        raise ValueError("no line items compared")
    return quantise(matched / compared)


def _count(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    collection = values[0] if values else []
    if not isinstance(collection, (list, tuple)):
        raise ValueError("count expects a list")
    return quantise(Decimal(len(collection)))


def _responsive_bid_count(values: Sequence[Any], _params: Dict[str, str]) -> Decimal:
    """Bids not recorded as non-responsive.

    A bid whose `is_responsive` was never set is counted. The opposite default
    would shrink the bid count out of missing data and raise a quote-count breach
    that the event never evidenced.

    Reads through `resolve` rather than attribute access because evidence is
    re-verified after a JSON round trip, where a Bid is a plain dict.
    """
    bids = values[0] if values else []
    if not isinstance(bids, (list, tuple)):
        raise ValueError("responsive_bid_count expects a list of bids")
    count = 0
    for bid in bids:
        got = resolve(bid, "is_responsive")
        if not (got.found and got.value is False):
            count += 1
    return quantise(Decimal(count))


COMPUTATIONS: Dict[str, Callable[[Sequence[Any], Dict[str, str]], Decimal]] = {
    "mean": _mean,
    "coefficient_of_variation": _coefficient_of_variation,
    "relative_gap": _relative_gap,
    "stdev_of_ratios": _stdev_of_ratios,
    "shared_fraction": _shared_fraction,
    "count": _count,
    "responsive_bid_count": _responsive_bid_count,
}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@dataclass
class VerificationContext:
    """Everything the verifier is allowed to consult.

    Deliberately small. The verifier re-derives claims from the artefacts the
    review was given; anything it had to fetch could have changed since, and a
    check that passes against different data from the one it ran on has not been
    verified.
    """

    event: Any
    documents: Dict[str, str] = field(default_factory=dict)


def _evidence_value(evidence: Any, context: VerificationContext) -> Any:
    if isinstance(evidence, FieldEvidence):
        return evidence.observed
    if isinstance(evidence, DerivedEvidence):
        return Decimal(evidence.value)
    if isinstance(evidence, DocumentSpanEvidence):
        return evidence.quote
    return None


def verify_one(evidence: Any, context: VerificationContext) -> Optional[str]:
    """Re-derive one piece of evidence. Returns a problem, or None if it holds."""

    if isinstance(evidence, DocumentSpanEvidence):
        text = context.documents.get(evidence.source.kind.lower())
        if text is None:
            return f"no {evidence.source.kind} text available to check the quote against"
        span = " ".join(text[evidence.start : evidence.end].split())
        if span != " ".join(evidence.quote.split()):
            return (
                f"quote at [{evidence.start}:{evidence.end}] reads {span[:60]!r} "
                f"but the evidence claims {evidence.quote[:60]!r}"
            )
        return None

    if isinstance(evidence, FieldEvidence):
        resolution = resolve(context.event, evidence.field_path)
        if not resolution.found:
            return f"{evidence.field_path}: {resolution.outcome.value} -- {resolution.detail}"
        if _canonical(resolution.value) != _canonical(evidence.observed):
            return (
                f"{evidence.field_path} reads {resolution.value!r} "
                f"but the evidence claims {evidence.observed!r}"
            )
        held = apply_comparator(evidence.comparator, resolution.value, evidence.required)
        if held is None:
            return (
                f"{evidence.field_path}: comparison {evidence.comparator.value} against "
                f"{evidence.required!r} cannot be evaluated"
            )
        if not held:
            return (
                f"{evidence.field_path}: {evidence.observed!r} does not satisfy "
                f"{evidence.comparator.value} {evidence.required!r}"
            )
        return None

    if isinstance(evidence, AbsenceEvidence):
        supplied = evidence.scope_path in getattr(context.event, "provided_collections", set())
        if supplied != evidence.scope_declared_complete:
            return (
                f"{evidence.scope_path}: evidence claims declared_complete="
                f"{evidence.scope_declared_complete} but the event says {supplied}"
            )
        resolution = resolve(context.event, evidence.field_path)
        if resolution.found and resolution.value is not None:
            return f"{evidence.field_path}: claimed absent but resolves to {resolution.value!r}"
        return None

    if isinstance(evidence, DerivedEvidence):
        for nested in evidence.inputs:
            problem = verify_one(nested, context)
            if problem:
                return f"input to {evidence.computation}: {problem}"
        computation = COMPUTATIONS.get(evidence.computation)
        if computation is None:
            return f"unknown computation {evidence.computation!r}"
        try:
            recomputed = computation(
                [_evidence_value(i, context) for i in evidence.inputs], evidence.params
            )
        except Exception as e:
            return f"{evidence.computation} could not be re-run: {type(e).__name__}: {e}"
        if recomputed != Decimal(evidence.value):
            return (
                f"{evidence.computation} recomputes to {recomputed} "
                f"but the evidence claims {evidence.value}"
            )
        return None

    return f"unknown evidence kind {type(evidence).__name__}"


def verify_finding(finding: ProcurementFinding, context: VerificationContext) -> List[str]:
    """Every problem with one finding's evidence.

    A finding asserting a breach with no evidence at all is itself a problem. That
    is not pedantry: an empty evidence list is what a half-written check produces,
    and it would otherwise sail through verification untouched.
    """
    problems = [
        f"{finding.check_id}: {problem}"
        for problem in (verify_one(e, context) for e in finding.evidence)
        if problem
    ]

    if not finding.evidence and finding.status in {
        CheckStatus.BREACH,
        CheckStatus.INDICATOR,
        CheckStatus.PASS,
    }:
        problems.append(f"{finding.check_id}: status {finding.status.value} with no evidence")

    if finding.status in {CheckStatus.BREACH, CheckStatus.PASS}:
        # The structural half of UNKNOWN != FALSE. A breach resting on the absence
        # of something inside a collection nobody said they supplied is a breach
        # resting on ignorance, and the same goes for a clean bill of health.
        for evidence in finding.evidence:
            if isinstance(evidence, AbsenceEvidence) and not evidence.scope_declared_complete:
                problems.append(
                    f"{finding.check_id}: {finding.status.value} rests on {evidence.field_path} "
                    f"being absent, but '{evidence.scope_path}' was never declared supplied -- "
                    "that is UNDETERMINED, not a finding"
                )
    return problems


def verify_findings(
    findings: Sequence[ProcurementFinding], context: VerificationContext
) -> Dict[str, List[str]]:
    """Problems per finding, keyed by check_id and subject.

    Keyed rather than flat so the compiler can drop exactly the findings that
    failed, as `contract_compiler` drops ungrounded ones, instead of discarding a
    whole review because one check was wrong.
    """
    problems: Dict[str, List[str]] = {}
    for finding in findings:
        found = verify_finding(finding, context)
        if found:
            problems[f"{finding.check_id}|{finding.subject_ref or ''}"] = found
    return problems


__all__ = [
    "COMPUTATIONS",
    "Outcome",
    "Resolution",
    "VerificationContext",
    "apply_comparator",
    "quantise",
    "resolve",
    "verify_finding",
    "verify_findings",
    "verify_one",
]
