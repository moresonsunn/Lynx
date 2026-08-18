# Test allowlist functionality
from compat.allowlist import check_force_side, check_user_override, set_override, get_effective_side

# Test force_server
print("Testing force_server...")
assert check_force_side("cobblemon") == "server"
assert check_force_side("fabric-api") == "server"
assert check_force_side("geckolib") == "server"
assert check_force_side("unknown-mod") is None
print("  force_server checks passed!")

# Test force_client
print("Testing force_client...")
assert check_force_side("sodium") == "client"
assert check_force_side("iris") == "client"
assert check_force_side("optifine") == "client"
print("  force_client checks passed!")

# Test user overrides
print("Testing user overrides...")
set_override("custom-mod", "server")
assert check_user_override("custom-mod") == "server"
set_override("custom-mod-2", "client")
assert check_user_override("custom-mod-2") == "client"
set_override("custom-mod-3", "both")
assert check_user_override("custom-mod-3") == "both"
print("  user overrides work!")

# Test get_effective_side
print("Testing get_effective_side...")
# User override takes precedence
side, reason = get_effective_side("custom-mod", "Custom Mod", "CLIENT", 0.9)
assert side == "server" and reason == "user_override"

# Allowlist takes precedence over detection
side, reason = get_effective_side("sodium", "Sodium", "BOTH", 0.9)
assert side == "client" and reason == "allowlist"

# High confidence detection
side, reason = get_effective_side("unknown-mod", "Unknown", "CLIENT", 0.9)
assert side == "client" and reason == "detected_high_conf"

# Low confidence detection -> unknown
side, reason = get_effective_side("unknown-mod-2", "Unknown", "CLIENT", 0.5)
assert side == "unknown" and reason == "insufficient_evidence"

# BOTH with high confidence
side, reason = get_effective_side("unknown-mod-3", "Unknown", "BOTH", 0.9)
assert side == "both" and reason == "detected_high_conf"

print("  get_effective_side works!")

print("All allowlist tests passed!")