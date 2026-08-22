"""Assemble the pure :class:`InterdictionService` from a container plus the loaded packs.

The orchestrator is pure and takes its rule packs and scam lexicon as already-parsed values, so
this thin factory is where the YAML seam (``rulepacks_loader``) meets the DI container (``config``).
It lives outside ``domain/`` because it depends on both. Every surface (API, CLI, agent) builds its
service here, so they share one wiring and cannot drift on which ports or packs the engine sees.
"""

from __future__ import annotations

from .config import Container, build_container
from .domain.interdiction_service import InterdictionService
from .rulepacks_loader import load_packs, load_scam_lexicon


def build_service(container: Container | None = None) -> InterdictionService:
    """Build the interdiction orchestrator, binding every port from the active profile."""
    resolved = container or build_container()
    return InterdictionService(
        features=resolved.features,
        warning_generator=resolved.warning_generator,
        audit=resolved.audit,
        tracer=resolved.tracer,
        conversation_channel=resolved.conversation_channel,
        packs=load_packs(),
        lexicon=load_scam_lexicon(),
    )
