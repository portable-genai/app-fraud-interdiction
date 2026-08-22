"""Scam-call lexicon scanning: deterministic phrase hits from a voice transcript.

The scam lexicon (the coached phrases a victim is talked into saying, the pressure cues, the
"do not tell the bank" scripts) is VERTICAL policy and lives in this repo (``rulepacks/``), not
in the shared speech kernel: the kernel carries the matcher, the consumer carries the phrases,
so a wording change is a pack edit here rather than a release of a package every repo pins. The
kernel's :func:`speech_lexicon_kit.find_hits` does the locale-sensitive matching, so a hit is
byte-identical across replays and across processes.

A hit is a FEATURE, never a verdict. The number of distinct scam-cue entries a call triggers is
fed to the deterministic engine as ``scam_call_lexicon_hits`` and thresholded there like any
other feature. This module is pure: :mod:`speech_lexicon_kit` is itself standard-library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from speech_lexicon_kit import (
    ChannelRole,
    Lexicon,
    LexiconEntry,
    LocaleMismatchError,
    PhraseSpec,
    Transcript,
    find_hits,
)

from .kernel import Citation
from .models import FeatureValue, ScamLexiconHit

#: The feature key the engine thresholds. One name, shared by the scanner and the rule packs.
SCAM_HITS_FEATURE = "scam_call_lexicon_hits"

#: The role whose speech is scanned. A scam victim is COACHED to repeat the scammer's lines, so
#: it is the customer's turns that carry the cue, not the agent's.
_SCANNED_ROLES = (ChannelRole.CUSTOMER,)


def build_lexicon(data: Mapping[str, Any]) -> Lexicon:
    """Parse an in-repo scam lexicon pack into the kernel's :class:`Lexicon`. Pure, no I/O."""
    entries = tuple(
        LexiconEntry(
            entry_id=str(row["entry_id"]),
            tags=tuple(str(tag) for tag in row.get("tags", ())),
            phrases=tuple(
                PhraseSpec(phrase_id=str(p["phrase_id"]), text=str(p["text"]))
                for p in row["phrases"]
            ),
        )
        for row in data["entries"]
    )
    return Lexicon(
        lexicon_id=str(data["lexicon_id"]),
        locale=str(data["locale"]),
        version=str(data.get("version", "v1")),
        entries=entries,
    )


def scan(transcript: Transcript, lexicon: Lexicon) -> tuple[ScamLexiconHit, ...]:
    """Return the scam-cue hits in ``transcript``, or an empty tuple when the call is out of scope.

    A :class:`~speech_lexicon_kit.LocaleMismatchError` (no turn is in the lexicon's language) is
    treated as "this call is not in a language this pack scores" and yields no hits, rather than
    failing the whole interdiction: the voice channel is one enrichment among many, and a payment
    verdict must never depend on a call being present or in a particular language.
    """
    try:
        hits = find_hits(transcript, lexicon, roles=_SCANNED_ROLES)
    except LocaleMismatchError:
        return ()
    seen: set[str] = set()
    out: list[ScamLexiconHit] = []
    for hit in hits:
        if hit.entry_id in seen:
            continue
        seen.add(hit.entry_id)
        out.append(
            ScamLexiconHit(
                phrase_id=hit.phrase_id,
                turn_index=hit.turn_index,
                citation=Citation(
                    source_id=f"scam-lexicon:{lexicon.lexicon_id}:{hit.entry_id}",
                    title="Scam-call cue",
                    snippet=hit.matched_text,
                ),
            )
        )
    return tuple(out)


def hits_feature(hits: tuple[ScamLexiconHit, ...]) -> FeatureValue:
    """Fold the distinct scam-cue hits into the single numeric feature the engine thresholds."""
    return FeatureValue(
        key=SCAM_HITS_FEATURE,
        value=float(len(hits)),
        citation=Citation(
            source_id="scam-lexicon:hit-count",
            title="Scam-call cues detected",
            snippet=f"{len(hits)} distinct scam-cue entries on the linked call",
        ),
    )
