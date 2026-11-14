"""Lynx Multi-Core Engine (LMCE) - Multi-Core Server Performance Execution Core.

Provides hardware core topology detection, thread pool profiling, core-scaled JVM argument
synthesis, Forge/NeoForge user_jvm_args.txt integration, and Universal Java Agent deployment.
"""

from .agent_manager import (
    AGENT_JAR_NAME,
    build_agent_jar,
    ensure_agent_binary,
    validate_agent_jar,
)
from .concurrency_profile import (
    ConcurrencyProfile,
    JvmProfile,
    MultiCoreConfig,
    detect_available_cores,
    detect_hardware_cores,
    get_concurrency_profile,
)
from .jvm_args_builder import (
    build_env_vars,
    build_multicore_jvm_args,
    format_user_jvm_args,
    prepare_server_multicore_env,
    quote_jvm_arg,
    write_user_jvm_args,
)

__all__ = [
    "ConcurrencyProfile",
    "MultiCoreConfig",
    "JvmProfile",
    "detect_hardware_cores",
    "detect_available_cores",
    "get_concurrency_profile",
    "build_multicore_jvm_args",
    "format_user_jvm_args",
    "quote_jvm_arg",
    "write_user_jvm_args",
    "build_env_vars",
    "prepare_server_multicore_env",
    "ensure_agent_binary",
    "validate_agent_jar",
    "build_agent_jar",
    "AGENT_JAR_NAME",
]
