"""Evidence subsystem: collectors, fusion and the gathering engine."""

from .context import AnalysisContext
from .engine import gather_evidence, group_by_claim
from .fusion import dominant_negative, fuse, sigmoid
from .collectors import default_collectors

__all__ = [
    "AnalysisContext",
    "gather_evidence",
    "group_by_claim",
    "fuse",
    "sigmoid",
    "dominant_negative",
    "default_collectors",
]
