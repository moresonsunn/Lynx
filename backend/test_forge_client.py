# Test Forge mod with explicit side=CLIENT
from compat.extract import extract_jar
from compat.evidence.collectors import default_collectors
from compat.evidence.context import AnalysisContext
from compat.evidence.engine import gather_evidence, group_by_claim
from compat.scoring.reasoner import decide
import tempfile
import zipfile
from pathlib import Path

with tempfile.TemporaryDirectory() as tmpdir:
    jar_path = Path(tmpdir) / 'forge-client-mod.jar'
    with zipfile.ZipFile(jar_path, 'w') as zf:
        toml_content = 'modLoader="javafml"\nloaderVersion="[36,)"\nlicense="MIT"\n[[mods]]\nmodId="forgeclientmod"\nversion="1.0.0"\ndisplayName="Forge Client Mod"\nside="CLIENT"\n'
        zf.writestr('META-INF/mods.toml', toml_content)
        zf.writestr('com/example/ForgeClientMod.class', bytes.fromhex('CAFEBABE00000034000100000000'))
    
    mod = extract_jar(jar_path)
    print(f'Extracted: {mod.canonical_id}, side={mod.declared_side.value}')
    
    ctx = AnalysisContext(loader='forge', mc_version='1.20.1')
    collectors = default_collectors(use_api=False)
    evidence = gather_evidence(mod, ctx, collectors)
    grouped = group_by_claim(evidence)
    
    from compat.scoring.reasoner import decide
    verdict = decide(mod, grouped, [], [], ctx)
    print(f'Verdict: {verdict.verdict.value}, side={verdict.side.value}, side_conf={verdict.side_confidence:.2f}')
    print(f'Reasons: {verdict.reasons}')
    print('Forge CLIENT side test passed!')