"""Load the per-market rule packs and the scam lexicon from ``rulepacks/`` (the ONE YAML seam).

The engine and the domain are pure standard library, so the YAML read lives here rather than in
``domain/``: this module depends on a YAML parser, parses each file into a frozen
:class:`~app_fraud_interdiction.domain.rulepack.RulePack` (or a
:class:`~speech_lexicon_kit.Lexicon`), and hands those pure values to the orchestrator. A malformed
pack is refused at load time, not discovered at scoring time.

Packs are DATA a policy owner reviews. Adding a market is a new ``rulepacks/<market>.yaml`` file
plus a locale row in ``domain/interdiction_service.py``; no engine code changes, which is the
whole point of keeping the numbers out of the code.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from speech_lexicon_kit import Lexicon

from .domain.rulepack import RulePack
from .domain.scam_lexicon import build_lexicon

#: The packs live at the repository root, resolved from this module rather than from the process
#: working directory, so the loader works whatever directory a surface is launched from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = _REPO_ROOT / "rulepacks"

#: The market packs shipped in-repo. A new market adds a file here and a row to this tuple.
MARKET_FILES: dict[str, str] = {"SG": "sg_app.yaml", "AU": "au_scam_duty.yaml"}

_SCAM_LEXICON_FILE = "scam_lexicon.yaml"


def _read_yaml(name: str) -> dict[str, Any]:
    path = PACKS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"rule pack {path} is missing")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"rule pack {path} must contain a mapping at the top level")
    return loaded


@lru_cache(maxsize=1)
def load_packs() -> dict[str, RulePack]:
    """Every market pack, keyed by market code. Cached: the files do not change at runtime."""
    packs: dict[str, RulePack] = {}
    for market, filename in MARKET_FILES.items():
        pack = RulePack.from_mapping(_read_yaml(filename))
        if pack.market != market:
            raise ValueError(
                f"pack {filename} declares market {pack.market!r} but is registered as {market!r}"
            )
        packs[market] = pack
    return packs


@lru_cache(maxsize=1)
def load_scam_lexicon() -> Lexicon:
    """The in-repo scam-cue lexicon, parsed into the speech kernel's :class:`Lexicon`."""
    return build_lexicon(_read_yaml(_SCAM_LEXICON_FILE))
