import React, { useEffect, useMemo, useState } from 'react';
import { FaLayerGroup, FaPlusCircle, FaDice, FaSearch, FaFileArchive, FaCube, FaCloudUploadAlt, FaChevronLeft, FaChevronRight, FaDownload } from 'react-icons/fa';
import { normalizeRamInput } from '../utils/ram';
import { useTranslation } from '../i18n/I18nContext';

const SERVER_TYPES_WITH_LOADER = ['fabric', 'forge', 'neoforge'];
const SERVER_TYPES = ['paper', 'purpur', 'vanilla', 'snapshot', 'fabric', 'forge', 'neoforge', 'mohist', 'magma', 'banner', 'catserver', 'spongeforge', 'bungeecord', 'velocity'];

export default function TemplatesPage({
  API,
  authHeaders,
  onCreateServer,
  types = [],
  versionsData,
  selectedType: createSelectedType,
  setSelectedType: setCreateSelectedType,
  name: createName,
  setName: setCreateName,
  version: createVersion,
  setVersion: setCreateVersion,
  hostPort: createHostPort,
  setHostPort: setCreateHostPort,
  minRam: createMinRam,
  setMinRam: setCreateMinRam,
  maxRam: createMaxRam,
  setMaxRam: setCreateMaxRam,
  loaderVersion: createLoaderVersion,
  setLoaderVersion: setCreateLoaderVersion,
  loaderVersionsData: createLoaderVersionsData,
  installerVersion: createInstallerVersion,
  setInstallerVersion: setCreateInstallerVersion,
}) {
  const { t } = useTranslation();
  const safeAuthHeaders = useMemo(() => (typeof authHeaders === 'function' ? authHeaders : () => ({})), [authHeaders]);

  const generateRandomName = () => {
    const adjectives = ['epic', 'swift', 'brave', 'cosmic', 'noble', 'mystic', 'crystal', 'shadow', 'iron', 'golden'];
    const nouns = ['realm', 'world', 'forge', 'craft', 'land', 'haven', 'peak', 'core', 'vault', 'nexus'];
    const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
    const noun = nouns[Math.floor(Math.random() * nouns.length)];
    const num = Math.floor(Math.random() * 1000);
    return `${adj}-${noun}-${num}`;
  };

  const [serverName, setServerName] = useState(generateRandomName);
  const [hostPort, setHostPort] = useState('');
  const [minRam, setMinRam] = useState('1024M');
  const [maxRam, setMaxRam] = useState('4096M');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [zipFile, setZipFile] = useState(null);
  const [javaOverride, setJavaOverride] = useState('');
  const [serverDefaults, setServerDefaults] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function loadServerDefaults() {
      try {
        const response = await fetch(`${API}/settings`, { headers: safeAuthHeaders() });
        if (response.ok) {
          const settings = await response.json();
          if (!cancelled && settings.server_defaults) {
            const defaults = settings.server_defaults;
            setServerDefaults(defaults);
            if (defaults.memory_min_mb) {
              setMinRam(`${defaults.memory_min_mb}M`);
              try { if (typeof setCreateMinRam === 'function') setCreateMinRam(String(defaults.memory_min_mb)); } catch (e) { }
            }
            if (defaults.memory_max_mb) {
              setMaxRam(`${defaults.memory_max_mb}M`);
              try { if (typeof setCreateMaxRam === 'function') setCreateMaxRam(String(defaults.memory_max_mb)); } catch (e) { }
            }
            if (defaults.java_args) setJavaOverride(defaults.java_args);
          }
        }
      } catch (e) { console.error('Failed to load server defaults:', e); }
    }
    loadServerDefaults();
    return () => { cancelled = true; };
  }, [API, safeAuthHeaders]);

  const [providers] = useState([
    { id: 'modrinth', name: 'Modrinth' },
    { id: 'curseforge', name: 'CurseForge' },
  ]);
  const [provider, setProvider] = useState('modrinth');
  const [catalogQuery, setCatalogQuery] = useState('');
  const [catalogLoader, setCatalogLoader] = useState('');
  const [catalogMC, setCatalogMC] = useState('');
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const [catalogResults, setCatalogResults] = useState([]);
  const [catalogPage, setCatalogPage] = useState(1);
  const CATALOG_PAGE_SIZE = 24;

  const [installOpen, setInstallOpen] = useState(false);
  const [installPack, setInstallPack] = useState(null);
  const [installProvider, setInstallProvider] = useState('modrinth');
  const [installVersions, setInstallVersions] = useState([]);
  const [installVersionId, setInstallVersionId] = useState('');
  const [installEvents, setInstallEvents] = useState([]);
  const [installWorking, setInstallWorking] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    async function suggest() {
      if (createHostPort) return;
      try {
        const r = await fetch(`${API}/ports/suggest?start=25565&end=25999`, { signal: controller.signal });
        if (!r.ok) return;
        const d = await r.json();
        if (!controller.signal.aborted && d?.port) setCreateHostPort(String(d.port));
      } catch { }
    }
    suggest();
    return () => controller.abort();
  }, [API, createHostPort, setCreateHostPort]);

  async function searchCatalog() {
    setCatalogLoading(true);
    setCatalogError('');
    try {
      const params = new URLSearchParams();
      if (catalogQuery) params.set('q', catalogQuery);
      if (catalogLoader) params.set('loader', catalogLoader);
      if (catalogMC) params.set('mc_version', catalogMC);
      params.set('provider', provider);
      params.set('page', String(catalogPage));
      params.set('page_size', String(CATALOG_PAGE_SIZE));
      const response = await fetch(`${API}/catalog/search?${params.toString()}`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setCatalogError(data?.detail || `HTTP ${response.status}`);
        setCatalogResults([]);
        return;
      }
      setCatalogResults(Array.isArray(data?.results) ? data.results : []);
    } catch (error) {
      setCatalogError(String(error.message || error));
    } finally {
      setCatalogLoading(false);
    }
  }

  useEffect(() => {
    searchCatalog();
  }, [catalogPage, provider]);

  async function openInstallFromCatalog(pack, options = {}) {
    setInstallPack(pack);
    setInstallOpen(true);
    setInstallEvents([]);
    setInstallWorking(false);

    // Auto-fill suggested name
    if (options.suggestedName) setServerName(options.suggestedName);
    if (options.recommendedRam?.min) setMinRam(options.recommendedRam.min);
    if (options.recommendedRam?.max) setMaxRam(options.recommendedRam.max);

    try {
      const chosenProvider = options.providerOverride || provider || 'modrinth';
      setInstallProvider(chosenProvider);
      const packIdentifier = pack.id || pack.slug || pack.project_id || pack.projectSlug;
      if (!packIdentifier) throw new Error('Missing pack identifier');

      const response = await fetch(
        `${API}/catalog/${chosenProvider}/packs/${encodeURIComponent(String(packIdentifier))}/versions`,
        { headers: safeAuthHeaders() }
      );
      const data = await response.json().catch(() => ({}));
      const versions = Array.isArray(data?.versions) ? data.versions : [];
      setInstallVersions(versions);

      if (options.versionOverride) {
        const match = versions.find(v => String(v.id) === String(options.versionOverride));
        setInstallVersionId(match ? String(match.id) : (versions[0]?.id || ''));
      } else {
        setInstallVersionId(versions[0]?.id || '');
      }
    } catch (error) {
      setInstallVersions([]);
      setInstallVersionId('');
      setInstallEvents(prev => [...prev, { type: 'error', message: String(error?.message || error) }]);
    }
  }

  async function submitInstall() {
    if (!installPack) return;
    if (!serverName || !String(serverName).trim()) {
      setInstallEvents(prev => [...prev, { type: 'error', message: 'Server name is required' }]);
      return;
    }
    setInstallWorking(true);
    setInstallEvents([{ type: 'progress', message: 'Submitting install task...' }]);
    try {
      const body = {
        provider: installProvider || provider || 'modrinth',
        pack_id: String(installPack.id || installPack.slug || ''),
        version_id: installVersionId ? String(installVersionId) : null,
        name: String(serverName).trim(),
        host_port: hostPort ? Number(hostPort) : null,
        min_ram: minRam,
        max_ram: maxRam,
      };
      const response = await fetch(`${API}/modpacks/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...safeAuthHeaders() },
        body: JSON.stringify(body)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

      const taskId = data?.task_id;
      if (!taskId) throw new Error('No task id');

      const es = new EventSource(`${API}/modpacks/install/events/${taskId}`);
      es.onmessage = event => {
        try {
          const parsed = JSON.parse(event.data);
          setInstallEvents(prev => {
            const next = [...prev, parsed];
            return next.length > 500 ? next.slice(-500) : next;
          });
          if (parsed.type === 'done' || parsed.type === 'error') {
            es.close();
            setInstallWorking(false);
          }
        } catch { }
      };
      es.onerror = () => {
        try { es.close(); } catch { }
        setInstallWorking(false);
      };
    } catch (error) {
      setInstallEvents(prev => [...prev, { type: 'error', message: String(error.message || error) }]);
      setInstallWorking(false);
    }
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in max-w-7xl mx-auto">
      <div className="flex items-center gap-3 border-b border-white/10 pb-6">
        <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-green-600 to-emerald-800 flex items-center justify-center shadow-lg shadow-green-900/20">
          <FaCube className="text-2xl text-white" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-white tracking-tight">
            Minecraft
          </h1>
          <p className="text-white/60">Create servers, install modpacks, or import local files.</p>
        </div>
      </div>

      {/* 1. Create Server Section */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
          <FaPlusCircle className="text-brand-400" /> {t('templates.createNewServer')}
        </h3>

        <form onSubmit={(e) => { if (onCreateServer) { onCreateServer(e); } else { e.preventDefault(); } }} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-semibold text-white/50 mb-1 uppercase tracking-wider">{t('servers.serverName')}</label>
              <input
                type="text"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                className="w-full px-4 py-2.5 bg-black/20 border border-white/10 rounded-lg text-white focus:border-brand-500 transition-colors"
                placeholder="My Awesome Server"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-white/50 mb-1 uppercase tracking-wider">Type</label>
              <select
                value={createSelectedType}
                onChange={(e) => setCreateSelectedType(e.target.value)}
                className="w-full px-3 py-2.5 bg-white/10 border border-white/10 rounded-lg text-white"
              >
                {(types || SERVER_TYPES).map((t) => (
                  <option key={t} value={t} style={{ backgroundColor: '#1f2937' }}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-white/50 mb-1 uppercase tracking-wider">Version</label>
              <select
                value={createVersion}
                onChange={(e) => setCreateVersion(e.target.value)}
                className="w-full px-3 py-2.5 bg-white/10 border border-white/10 rounded-lg text-white"
              >
                {(versionsData?.versions || []).map((v) => (
                  <option key={v} value={v} style={{ backgroundColor: '#1f2937' }}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          {SERVER_TYPES_WITH_LOADER.includes(createSelectedType) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-white/5 p-4 rounded-lg border border-white/5">
              <div>
                <label className="block text-xs text-white/60 mb-1">{t('templatesPage.loaderVersion')}</label>
                <select
                  value={createLoaderVersion}
                  onChange={(e) => setCreateLoaderVersion(e.target.value)}
                  className="w-full px-3 py-2 bg-black/20 border border-white/10 rounded text-sm text-white"
                >
                  {(createLoaderVersionsData?.loader_versions || []).map((lv) => (
                    <option key={lv} value={lv} style={{ backgroundColor: '#1f2937' }}>{lv}</option>
                  ))}
                </select>
              </div>
              {createSelectedType === 'fabric' && (
                <div>
                  <label className="block text-xs text-white/60 mb-1">{t('templatesPage.installerVersion')}</label>
                  <input
                    type="text"
                    value={createInstallerVersion}
                    onChange={(e) => setCreateInstallerVersion(e.target.value)}
                    className="w-full px-3 py-2 bg-black/20 border border-white/10 rounded text-sm text-white"
                    placeholder="Latest"
                  />
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs text-white/50 mb-1">Port (Optional)</label>
              <input
                type="number"
                value={createHostPort}
                onChange={(e) => setCreateHostPort(e.target.value)}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
                placeholder="25565"
              />
            </div>
            <div>
              <label className="block text-xs text-white/50 mb-1">{t('templatesPage.minRam')}</label>
              <input
                value={createMinRam}
                onChange={(e) => setCreateMinRam(e.target.value)}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
              />
            </div>
            <div>
              <label className="block text-xs text-white/50 mb-1">{t('templatesPage.maxRam')}</label>
              <input
                value={createMaxRam}
                onChange={(e) => setCreateMaxRam(e.target.value)}
                className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-white"
              />
            </div>
          </div>

          <div className="pt-2">
            <button
              type="submit"
              className="bg-brand-600 hover:bg-brand-500 text-white px-6 py-3 rounded-lg font-bold shadow-lg shadow-brand-500/20 transition-all flex items-center gap-2"
            >
              <FaPlusCircle /> {t('templatesPage.createServer')}
            </button>
          </div>
        </form>
      </div>

      {/* 2. Import ZIP Section */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
          <FaFileArchive className="text-yellow-400" /> {t('templatesPage.importServerPack')}
        </h3>
        <div className="space-y-6">
          <div>
            <label className="block text-xs font-semibold text-white/50 mb-1 uppercase">{t('templatesPage.serverName')}</label>
            <div className="flex gap-2">
              <input
                value={serverName}
                onChange={e => setServerName(e.target.value)}
                className="flex-1 rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white focus:border-brand-500 transition-colors"
                placeholder="My Awesome Server"
              />
              <button
                onClick={() => setServerName(generateRandomName())}
                className="p-2 rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
                title={t('templatesPage.generateRandomName')}
              >
                <FaDice />
              </button>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-white/50 mb-2 uppercase">{t('templatesPage.serverPackFile')}</label>
            <div className="relative group">
              <input
                type="file"
                accept=".zip"
                onChange={event => setZipFile(event.target.files && event.target.files[0] ? event.target.files[0] : null)}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
              />
              <div className={`border-2 border-dashed rounded-xl p-6 transition-all text-center flex flex-col items-center gap-3 ${zipFile ? 'border-brand-500 bg-brand-500/10' : 'border-white/10 group-hover:border-white/20 bg-black/20 group-hover:bg-black/30'}`}>
                <div className={`p-3 rounded-full transition-colors ${zipFile ? 'bg-brand-500 text-white' : 'bg-white/5 text-white/50 group-hover:text-white'}`}>
                  {zipFile ? <FaFileArchive size={20} /> : <FaCloudUploadAlt size={20} />}
                </div>
                <div>
                  <div className="font-semibold text-white text-sm">{zipFile ? zipFile.name : 'Click or drop ZIP file here'}</div>
                  <div className="text-xs text-white/40 mt-1">{zipFile ? (zipFile.size / 1024 / 1024).toFixed(2) + ' MB' : 'Select a modpack .zip file to import'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
          <div>
            <label className="block text-xs font-semibold text-white/50 mb-1">PORT (OPTIONAL)</label>
            <input
              type="number"
              className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
              placeholder="25565"
              value={hostPort}
              onChange={e => setHostPort(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-white/50 mb-1">MIN RAM</label>
            <input
              className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
              value={minRam}
              onChange={e => setMinRam(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-white/50 mb-1">MAX RAM</label>
            <input
              className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
              value={maxRam}
              onChange={e => setMaxRam(e.target.value)}
            />
          </div>
        </div>

        <div className="mt-4">
          <button
            disabled={busy || !zipFile}
            onClick={async () => {
              setBusy(true); setMsg('');
              try {
                const normMin = normalizeRamInput(minRam);
                const normMax = normalizeRamInput(maxRam);
                if (!normMin || !normMax) { throw new Error('Invalid RAM'); }
                const formData = new FormData();
                formData.append('server_name', serverName);
                if (hostPort) formData.append('host_port', hostPort);
                formData.append('min_ram', normMin);
                formData.append('max_ram', normMax);
                if (zipFile) formData.append('file', zipFile);
                await fetch(`${API}/modpacks/import-upload`, { method: 'POST', headers: safeAuthHeaders(), body: formData });
                setMsg('Success! Check Servers tab.');
              } catch (e) { setMsg('Error: ' + e.message); }
              finally { setBusy(false); }
            }}
            className="bg-yellow-600/80 hover:bg-yellow-600 text-white px-6 py-2 rounded-lg font-medium shadow-lg transition-all disabled:opacity-50"
          >
            {busy ? 'Uploading...' : 'Import ZIP'}
          </button>
          {msg && <div className="mt-2 text-xs text-white/60">{msg}</div>}
        </div>
      </div>

      {/* 3. Catalog Section */}
      <div className="bg-white/5 border border-white/10 rounded-xl p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h3 className="text-xl font-bold flex items-center gap-2">
              <FaSearch className="text-blue-400" /> {t('templatesPage.modpackCatalog')}
            </h3>
            <p className="text-sm text-white/60">{t('templatesPage.searchModrinthCurseforge')}</p>
          </div>

          <div className="flex items-center gap-2 bg-black/20 p-1 rounded-lg border border-white/5">
            {providers.map(p => (
              <button
                key={p.id}
                onClick={() => { setProvider(p.id); setCatalogPage(1); }}
                className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-all ${provider === p.id ? 'bg-blue-600 text-white shadow' : 'text-white/50 hover:text-white'}`}
              >
                {p.name}
              </button>
            ))}
          </div>
        </div>

        <div className="flex gap-2 mb-6">
          <input
            className="flex-1 rounded-lg bg-black/20 border border-white/10 px-4 py-2 text-white focus:outline-none focus:border-blue-500 transition-colors"
            placeholder={t('templatesPage.searchModpacks')}
            value={catalogQuery}
            onChange={e => setCatalogQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && searchCatalog()}
          />
          <button
            onClick={() => { setCatalogPage(1); searchCatalog(); }}
            className="px-6 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-semibold shadow-lg shadow-blue-500/20 transition-all"
          >
            Search
          </button>
        </div>

        {catalogLoading && (
          <div className="flex justify-center py-20">
            <div className="animate-spin w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full" />
          </div>
        )}

        {!catalogLoading && catalogResults.length === 0 && !catalogError && (
          <div className="text-center py-20 text-white/30 border-2 border-dashed border-white/5 rounded-xl">
            {catalogQuery ? 'No modpacks found matching your search.' : 'Start searching to find modpacks...'}
          </div>
        )}

        {!catalogLoading && catalogError && (
          <div className="bg-red-500/10 border border-red-500/20 text-red-200 p-4 rounded-xl text-center">
            {catalogError}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {catalogResults.map((pack) => (
            <div key={pack.id || pack.slug} className="group bg-white/5 border border-white/5 hover:border-brand-500/50 rounded-xl p-4 hover:bg-white/[0.07] transition-all duration-300 flex gap-4 hover:-translate-y-1 hover:shadow-xl">
              <div className="w-16 h-16 bg-black/40 rounded-lg flex-shrink-0 overflow-hidden shadow-inner relative">
                {pack.icon_url ? (
                  <img src={pack.icon_url} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-white/20"><FaCube size={24} /></div>
                )}
              </div>
              <div className="flex-1 min-w-0 flex flex-col">
                <h4 className="font-bold text-white truncate pr-2 group-hover:text-brand-400 transition-colors">{pack.name}</h4>
                <p className="text-xs text-white/60 line-clamp-2 mt-1 mb-auto">{pack.description}</p>
                <div className="flex items-center justify-between gap-3 mt-3 pt-3 border-t border-white/5">
                  <div className="flex items-center text-xs text-white/40 bg-black/20 px-2 py-1 rounded">
                    <FaDownload className="mr-1.5 opacity-70" /> {typeof pack.downloads === 'number' ? Intl.NumberFormat('en', { notation: 'compact' }).format(pack.downloads) : '0'}
                  </div>
                  <button
                    onClick={() => openInstallFromCatalog(pack)}
                    className="px-3 py-1.5 bg-white/10 hover:bg-brand-600 hover:text-white text-xs font-bold rounded-lg text-white/80 transition-all shadow-sm"
                  >
                    Install
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Pagination */}
        {catalogResults.length > 0 && (
          <div className="flex items-center justify-between mt-8 border-t border-white/5 pt-4">
            <button
              onClick={() => setCatalogPage(p => Math.max(1, p - 1))}
              disabled={catalogPage <= 1}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all text-white text-sm font-medium"
            >
              <FaChevronLeft size={12} /> Previous
            </button>

            <div className="text-sm font-medium text-white/50">
              Page <span className="text-white">{catalogPage}</span>
            </div>

            <button
              onClick={() => setCatalogPage(p => p + 1)}
              disabled={catalogResults.length < 24}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-all text-white text-sm font-medium"
            >
              Next <FaChevronRight size={12} />
            </button>
          </div>
        )}
      </div>

      {/* Install Modal */}
      {installOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-[#1a1b1e] border border-white/10 rounded-2xl w-full max-w-2xl max-h-[90vh] flex flex-col shadow-2xl">
            <div className="p-6 border-b border-white/10 flex items-center justify-between bg-white/5">
              <h3 className="text-xl font-bold text-white">Install {installPack?.name}</h3>
              <button onClick={() => setInstallOpen(false)} className="text-white/50 hover:text-white">&times;</button>
            </div>

            <div className="p-6 overflow-y-auto flex-1 space-y-6">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-white/50 mb-1">VERSION</label>
                  <select
                    className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
                    value={installVersionId}
                    onChange={e => setInstallVersionId(e.target.value)}
                  >
                    {installVersions.map(v => (
                      <option key={v.id} value={v.id}>{v.name || v.version_number}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-white/50 mb-1">SERVER NAME</label>
                  <input
                    className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
                    value={serverName}
                    onChange={e => setServerName(e.target.value)}
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-white/50 mb-1">PORT (OPTIONAL)</label>
                  <input
                    type="number"
                    className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
                    placeholder="25565"
                    value={hostPort}
                    onChange={e => setHostPort(e.target.value)}
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs font-semibold text-white/50 mb-1">MIN RAM</label>
                    <input
                      className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
                      value={minRam}
                      onChange={e => setMinRam(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-white/50 mb-1">MAX RAM</label>
                    <input
                      className="w-full rounded-lg bg-black/20 border border-white/10 px-3 py-2 text-white"
                      value={maxRam}
                      onChange={e => setMaxRam(e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <div className="bg-black/30 rounded-xl p-4 border border-white/5 h-48 overflow-auto font-mono text-xs">
                {installEvents.map((ev, i) => (
                  <div key={i} className={`mb-1 ${ev.type === 'error' ? 'text-red-400' : 'text-white/70'}`}>
                    {typeof ev.message === 'string' ? ev.message : JSON.stringify(ev)}
                  </div>
                ))}
                {installEvents.length === 0 && <div className="text-white/30 italic">Ready to install...</div>}
              </div>
            </div>

            <div className="p-6 border-t border-white/10 flex justify-end gap-3 bg-white/5">
              <button onClick={() => setInstallOpen(false)} className="px-4 py-2 rounded-lg text-white/60 hover:text-white hover:bg-white/5 transition-colors">Cancel</button>
              <button
                disabled={installWorking}
                onClick={submitInstall}
                className="px-6 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg font-bold shadow-lg shadow-brand-500/20 disabled:opacity-50"
              >
                {installWorking ? 'Installing...' : 'Start Installation'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
