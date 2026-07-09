"""Shared analysis context passed to every evidence collector."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..knowledge import KnowledgeBase, get_default_kb
from ..models import Loader
from ..versioning import ComparableVersion, parse_version


@dataclass
class AnalysisContext:
    loader: Loader = Loader.UNKNOWN
    mc_version: Optional[str] = None
    use_api: bool = True
    cf_api_key: Optional[str] = None
    kb: KnowledgeBase = field(default_factory=get_default_kb)
    _mc_parsed: Optional[ComparableVersion] = None

    @property
    def mc_parsed(self) -> Optional[ComparableVersion]:
        if self._mc_parsed is None and self.mc_version:
            self._mc_parsed = parse_version(self.mc_version)
        return self._mc_parsed
