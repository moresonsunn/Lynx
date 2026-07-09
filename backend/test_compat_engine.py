"""Unit tests for the multi-stage compatibility engine (``compat`` package).

All tests are offline (``use_api=False``): they build synthetic JARs in a temp
directory and assert on the graded output. Run with::

    python -m pytest backend/test_compat_engine.py -q
"""

import json
import sys
import zipfile
from pathlib import Path

# Make the backend package importable when tests run from the repo root.
_BACKEND = Path(__file__).resolve().parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import compat  # noqa: E402
from compat.evidence.fusion import dominant_negative, fuse  # noqa: E402
from compat.extract import extract_jar  # noqa: E402
from compat.graph import build_graph  # noqa: E402
from compat.models import Evidence, Loader, Side, Verdict  # noqa: E402
from compat.versioning import parse_range, parse_version  # noqa: E402


# ─────────────────────────────────────────────────────── jar builders
def _fabric_jar(path, mod_id, *, env="*", depends=None, provides=None,
                version="1.0.0", nested=None):
    manifest = {"id": mod_id, "name": mod_id, "version": version, "environment": env,
                "depends": depends or {"minecraft": "1.20.1"}}
    if provides:
        manifest["provides"] = provides
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("fabric.mod.json", json.dumps(manifest))
        z.writestr(f"{mod_id}/Main.class", b"\x00")
        if nested:
            for nname, ndata in nested.items():
                z.writestr(f"META-INF/jars/{nname}", ndata)


def _forge_jar(path, mod_id, *, mc="[1.20.1,1.21)", neo=False, deps=None,
               side=None, version="1.0.0", nested=None):
    lines = ['modLoader="javafml"', 'loaderVersion="[47,)"', "", "[[mods]]",
             f'modId="{mod_id}"', f'version="{version}"', f'displayName="{mod_id}"']
    if side:
        lines.append(f'side="{side}"')
    lines += ["", f"[[dependencies.{mod_id}]]", 'modId="minecraft"',
              "mandatory=true", f'versionRange="{mc}"', 'side="BOTH"']
    if neo:
        lines += ["", f"[[dependencies.{mod_id}]]", 'modId="neoforge"',
                  "mandatory=true", 'versionRange="[20,)"']
    for dep_id, (mand, rng) in (deps or {}).items():
        lines += ["", f"[[dependencies.{mod_id}]]", f'modId="{dep_id}"',
                  f"mandatory={'true' if mand else 'false'}", f'versionRange="{rng}"']
    toml = "\n".join(lines)
    fname = "META-INF/neoforge.mods.toml" if neo else "META-INF/mods.toml"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(fname, toml)
        z.writestr(f"{mod_id}/Main.class", b"\x00")
        if nested:
            for nname, ndata in nested.items():
                z.writestr(f"META-INF/jarjar/{nname}", ndata)


def _mods_dir(tmp_path):
    d = tmp_path / "mods"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────────────────────────────────────────────────────── versioning
def test_version_ordering():
    assert parse_version("1.0.0-rc1") < parse_version("1.0.0")
    assert parse_version("1.0.0") < parse_version("1.0.1")
    assert parse_version("1.20") < parse_version("1.20.1")
    assert parse_version("1.0.0-alpha") < parse_version("1.0.0-beta")
    assert parse_version("23w14a") < parse_version("1.20")
    assert parse_version("2.0.0") > parse_version("1.99.99")


def test_maven_ranges():
    r = parse_range("[1.20.1,1.21)")
    assert r.contains(parse_version("1.20.1")) is True
    assert r.contains(parse_version("1.20.4")) is True
    assert r.contains(parse_version("1.21")) is False
    assert r.contains(parse_version("1.19")) is False


def test_semver_operators():
    assert parse_range("^1.2.3").contains(parse_version("1.9.0")) is True
    assert parse_range("^1.2.3").contains(parse_version("2.0.0")) is False
    assert parse_range("~1.2.3").contains(parse_version("1.2.9")) is True
    assert parse_range("~1.2.3").contains(parse_version("1.3.0")) is False


def test_comparator_and_wildcard():
    assert parse_range(">=1.20 <1.21").contains(parse_version("1.20.5")) is True
    assert parse_range(">=1.20 <1.21").contains(parse_version("1.21")) is False
    assert parse_range("1.20.x").contains(parse_version("1.20.6")) is True
    assert parse_range("1.20.x").contains(parse_version("1.21.0")) is False
    assert parse_range("*").contains(parse_version("1.2.3")) is True


def test_unparseable_range_is_neutral():
    # Must be None (neutral), never False — "can't parse" != "incompatible".
    assert parse_range("some-garbage-string").contains(parse_version("1.0")) is None
    assert parse_range("").contains(parse_version("1.0")) is True  # empty == any


# ─────────────────────────────────────────────────────── extraction
def test_extract_forge_vs_neoforge(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "a.jar", "amod")
    _forge_jar(d / "b.jar", "bmod", neo=True)
    a = extract_jar(d / "a.jar")
    b = extract_jar(d / "b.jar")
    assert Loader.FORGE in a.loaders
    assert Loader.NEOFORGE in b.loaders  # not mislabeled forge
    assert a.canonical_id == "amod"


def test_extract_fabric_side_and_deps(tmp_path):
    d = _mods_dir(tmp_path)
    _fabric_jar(d / "c.jar", "cmod", env="client",
                depends={"minecraft": "1.20.1", "fabric-api": "*", "geckolib": "*"})
    c = extract_jar(d / "c.jar")
    assert Loader.FABRIC in c.loaders
    assert c.declared_side == Side.CLIENT
    dep_ids = {dep.target_id for dep in c.dependencies}
    assert "geckolib" in dep_ids
    assert "minecraft" not in dep_ids  # core ids become mc_ranges, not deps


def test_jar_in_jar_provides(tmp_path):
    d = _mods_dir(tmp_path)
    # build an inner library jar in memory
    import io
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("fabric.mod.json", json.dumps({"id": "embeddedlib", "version": "1.0.0"}))
    _fabric_jar(d / "host.jar", "hostmod", nested={"embeddedlib.jar": inner.getvalue()})
    host = extract_jar(d / "host.jar")
    assert any(e.canonical_id == "embeddedlib" for e in host.embedded)
    assert "embeddedlib" in host.provides  # embedded lib is provided, not missing


# ─────────────────────────────────────────────────────── fusion
def test_fusion_agreement_and_disagreement():
    pos = Evidence("jar", "x", +1.0, 3.0, 0.95, "a")
    p1, _ = fuse([pos])
    p2, _ = fuse([pos, Evidence("modrinth", "x", +1.0, 2.0, 0.85, "b")])
    assert p2 > p1  # agreement compounds

    # opposing evidence cancels -> ~0.5, low confidence
    p3, conf3 = fuse([pos, Evidence("jar", "x", -1.0, 3.0, 0.95, "c")])
    assert abs(p3 - 0.5) < 0.05
    assert conf3 < 0.1


def test_filename_cannot_gate():
    # A low-trust filename signal must not qualify as an authoritative veto.
    weak = Evidence("filename", "loader", -1.0, 0.6, 0.30, "filename says client")
    strong = Evidence("jar", "loader", -1.0, 3.0, 0.95, "jar says wrong loader")
    assert dominant_negative([weak]) is None
    assert dominant_negative([strong]) is not None


# ─────────────────────────────────────────────────────── graph
def test_graph_resolution_and_missing(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "lib.jar", "geckolib")
    _forge_jar(d / "user.jar", "usermod", deps={"geckolib": (True, "*"),
                                                 "absent": (True, "*")})
    mods = [extract_jar(p) for p in d.glob("*.jar")]
    graph = build_graph(mods)
    missing = {e.dep.target_id for e in graph.missing_required()}
    assert "absent" in missing
    assert "geckolib" not in missing  # satisfied by lib.jar


def test_graph_cycle_detection(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "x.jar", "xmod", deps={"ymod": (True, "*")})
    _forge_jar(d / "y.jar", "ymod", deps={"xmod": (True, "*")})
    mods = [extract_jar(p) for p in d.glob("*.jar")]
    graph = build_graph(mods)
    cycles = graph.cycles()
    assert cycles and any(set(c) == {"xmod", "ymod"} for c in cycles)


# ─────────────────────────────────────────────────────── end-to-end
def test_loader_mismatch_is_incompatible(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "forgey.jar", "forgey")
    _fabric_jar(d / "fabricy.jar", "fabricy")
    report = compat.analyze_pack(d, loader="forge", mc_version="1.20.1", use_api=False)
    by_name = {v.mod.filename: v for v in report.verdicts}
    assert by_name["fabricy.jar"].verdict == Verdict.INCOMPATIBLE
    assert by_name["forgey.jar"].verdict in (Verdict.COMPATIBLE,
                                             Verdict.COMPATIBLE_WITH_WARNINGS)


def test_mc_version_mismatch_is_incompatible(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "old.jar", "oldmod", mc="[1.16,1.17)")
    report = compat.analyze_pack(d, loader="forge", mc_version="1.20.1", use_api=False)
    assert report.verdicts[0].verdict == Verdict.INCOMPATIBLE


def test_client_only_detected_but_compatible(tmp_path):
    d = _mods_dir(tmp_path)
    _fabric_jar(d / "sodium.jar", "sodium", env="client")
    report = compat.analyze_pack(d, loader="fabric", mc_version="1.20.1", use_api=False)
    v = report.verdicts[0]
    assert v.side == Side.CLIENT
    assert v.is_client_only is True
    # It still *runs* on the matching loader, so it is not "incompatible".
    assert v.verdict in (Verdict.COMPATIBLE, Verdict.COMPATIBLE_WITH_WARNINGS)


def test_server_required_dependency_is_kept(tmp_path):
    d = _mods_dir(tmp_path)
    # geckolib is server-required (KB seed); a content mod depends on it.
    _forge_jar(d / "geckolib.jar", "geckolib")
    _forge_jar(d / "content.jar", "contentmod", deps={"geckolib": (True, "*")})
    report = compat.analyze_pack(d, loader="forge", mc_version="1.20.1", use_api=False)
    gecko = next(v for v in report.verdicts if v.mod.canonical_id == "geckolib")
    assert gecko.side != Side.CLIENT  # never filtered as client-only
    assert gecko.is_client_only is False


def test_known_pair_conflict(tmp_path):
    d = _mods_dir(tmp_path)
    _fabric_jar(d / "sodium.jar", "sodium")
    _fabric_jar(d / "optifine.jar", "optifine")
    report = compat.analyze_pack(d, loader="fabric", mc_version="1.20.1", use_api=False)
    kinds = {c.kind for c in report.conflicts}
    assert "known_pair" in kinds or "duplicate" in kinds


def test_duplicate_mod_id_conflict(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "jei-1.jar", "jei")
    _forge_jar(d / "jei-2.jar", "jei")
    report = compat.analyze_pack(d, loader="forge", mc_version="1.20.1", use_api=False)
    assert any(c.kind in ("mod_id_collision", "duplicate") for c in report.conflicts)


def test_report_is_serializable(tmp_path):
    d = _mods_dir(tmp_path)
    _forge_jar(d / "a.jar", "amod")
    report = compat.analyze_pack(d, loader="forge", mc_version="1.20.1", use_api=False)
    # Must round-trip to JSON for the API layer.
    json.dumps(report.to_dict())
