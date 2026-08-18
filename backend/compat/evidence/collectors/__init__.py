"""Evidence collector registry.

Order matters: Modrinth runs before GitHub so the GitHub collector can use the
source repository discovered from Modrinth metadata.
"""

from __future__ import annotations

from .base import EvidenceCollector, loader_compatibility
from .local import FilenameCollector, JarMetadataCollector, KnowledgeBaseCollector
from .remote import CurseForgeCollector, GitHubReleaseCollector, ModrinthCollector
from .bytecode_collector import BytecodeCollector
from .allowlist_collector import AllowlistCollector


def default_collectors(*, use_api: bool = True, use_bytecode: bool = True) -> list[EvidenceCollector]:
    collectors: list[EvidenceCollector] = [
        JarMetadataCollector(),
        KnowledgeBaseCollector(),
        FilenameCollector(),
        AllowlistCollector(),  # Check allowlist early for high-priority signals
    ]
    if use_bytecode:
        collectors.append(BytecodeCollector())
    if use_api:
        collectors += [
            ModrinthCollector(),
            CurseForgeCollector(),
            GitHubReleaseCollector(),
        ]
    return collectors


__all__ = [
    "EvidenceCollector",
    "loader_compatibility",
    "JarMetadataCollector",
    "KnowledgeBaseCollector",
    "FilenameCollector",
    "AllowlistCollector",
    "BytecodeCollector",
    "ModrinthCollector",
    "CurseForgeCollector",
    "GitHubReleaseCollector",
    "default_collectors",
]
