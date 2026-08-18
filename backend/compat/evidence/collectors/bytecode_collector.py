"""Bytecode evidence collector for client/server side detection.

Integrates bytecode scanning as a new evidence source in the compatibility engine.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import CanonicalMod, Evidence, Side
from ... import weights as W
from ..context import AnalysisContext
from .base import EvidenceCollector

logger = logging.getLogger(__name__)


class BytecodeCollector(EvidenceCollector):
    """Collects evidence from bytecode analysis of mod JARs."""

    name = "bytecode"

    def __init__(self, max_classes_per_jar: int = 500, enabled: bool = True):
        self.max_classes_per_jar = max_classes_per_jar
        self.enabled = enabled

    def collect(self, mod: CanonicalMod, ctx: AnalysisContext) -> list[Evidence]:
        if not self.enabled:
            return []

        ev: list[Evidence] = []

        # Skip if no path available
        if not mod.path:
            return ev

        jar_path = Path(mod.path)
        if not jar_path.exists() or not jar_path.is_file():
            return ev

        # Only scan mod JARs (not embedded/library jars)
        if jar_path.suffix.lower() != ".jar":
            return ev

        # Import here to avoid circular imports
        from ...extract.bytecode_scanner import scan_jar_for_bytecode_side, BytecodeSideResult

        try:
            result: BytecodeSideResult = scan_jar_for_bytecode_side(
                jar_path, max_classes=self.max_classes_per_jar
            )

            trust = W.trust("bytecode")

            # Log the scan result
            logger.debug(
                f"Bytecode scan for {mod.canonical_id}: side={result.side}, "
                f"conf={result.confidence:.3f}, classes={result.classes_scanned}, "
                f"client_refs={len(result.client_refs)}, server_refs={len(result.server_refs)}, "
                f"@OnlyIn(CLIENT)={result.only_in_client}, @OnlyIn(SERVER)={result.only_in_server}"
            )

            # Generate evidence based on bytecode analysis
            if result.side == "CLIENT" and result.confidence > 0.5:
                # Strong client-only signal
                polarity = -1.0
                weight = W.weight("bytecode_client") * result.confidence
                detail = (
                    f"Bytecode analysis: {result.side} (conf={result.confidence:.2f}, "
                    f"{result.classes_scanned} classes scanned). "
                    f"Client refs: {len(result.client_refs)}, "
                    f"@OnlyIn(CLIENT): {result.only_in_client}"
                )
                if result.client_refs:
                    detail += f" Examples: {', '.join(result.client_refs[:3])}"

                ev.append(Evidence(
                    source="bytecode",
                    claim="side",
                    polarity=polarity,
                    weight=weight,
                    trust=trust,
                    detail=detail,
                    freshness=1.0,
                ))

            elif result.side == "SERVER" and result.confidence > 0.5:
                # Server-side signal
                polarity = +1.0
                weight = W.weight("bytecode_server") * result.confidence
                detail = (
                    f"Bytecode analysis: {result.side} (conf={result.confidence:.2f}, "
                    f"{result.classes_scanned} classes scanned). "
                    f"Server refs: {len(result.server_refs)}, "
                    f"@OnlyIn(SERVER): {result.only_in_server}"
                )
                if result.server_refs:
                    detail += f" Examples: {', '.join(result.server_refs[:3])}"

                ev.append(Evidence(
                    source="bytecode",
                    claim="side",
                    polarity=polarity,
                    weight=weight,
                    trust=trust,
                    detail=detail,
                    freshness=1.0,
                ))

            elif result.side == "BOTH" and result.confidence > 0.4:
                # BOTH signal (weak positive for server)
                polarity = +0.5
                weight = W.weight("bytecode_both") * result.confidence
                detail = (
                    f"Bytecode analysis: {result.side} (conf={result.confidence:.2f}). "
                    f"Both client and server refs found."
                )
                ev.append(Evidence(
                    source="bytecode",
                    claim="side",
                    polarity=polarity,
                    weight=weight,
                    trust=trust,
                    detail=detail,
                    freshness=1.0,
                ))

            # If scan found @OnlyIn annotations, add high-confidence evidence
            if result.only_in_client:
                ev.append(Evidence(
                    source="bytecode",
                    claim="side",
                    polarity=-1.0,
                    weight=W.weight("onlyin_client"),
                    trust=trust,
                    detail=f"Bytecode contains @OnlyIn(Dist.CLIENT) annotation (classes={result.classes_scanned})",
                    freshness=1.0,
                ))
            elif result.only_in_server:
                ev.append(Evidence(
                    source="bytecode",
                    claim="side",
                    polarity=+1.0,
                    weight=W.weight("onlyin_server"),
                    trust=trust,
                    detail=f"Bytecode contains @OnlyIn(Dist.DEDICATED_SERVER) annotation (classes={result.classes_scanned})",
                    freshness=1.0,
                ))

        except Exception as e:
            logger.warning(f"Bytecode scan failed for {mod.canonical_id}: {e}")

        return ev


__all__ = ["BytecodeCollector"]