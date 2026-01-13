import React, { useEffect, useMemo, useState } from 'react';
import { FaLayerGroup, FaPlusCircle, FaDice } from 'react-icons/fa';
import { normalizeRamInput } from '../utils/ram';
import { useTranslation } from '../i18n/I18nContext';

const SERVER_TYPES_WITH_LOADER = ['fabric', 'forge', 'neoforge'];

const TMOD_WORLD_SIZE_OPTIONS = [
  { value: '1', label: 'Small' },
  { value: '2', label: 'Medium' },
  { value: '3', label: 'Large' },
];

const TMOD_WORLD_DIFFICULTY_OPTIONS = [
  { value: '0', label: 'Journey' },
  { value: '1', label: 'Classic' },
  { value: '2', label: 'Expert' },
  { value: '3', label: 'Master' },
];

const TMOD_WORLD_ENV_KEY_SET = new Set(['WORLD_NAME', 'WORLD_FILENAME', 'WORLD_SIZE', 'WORLD_DIFFICULTY', 'WORLD_SEED']);
const STEAM_PER_PAGE = 12;


const STEAM_CATEGORIES = [
  { id: 'all', label: 'All Games', keywords: [] },
  { id: 'survival', label: 'Survival', keywords: ['survival', 'zombie', 'craft', 'rust', 'ark', 'dayz', 'forest', 'valheim', 'conan', 'enshrouded', 'palworld', '7 days', 'scum', 'icarus', 'raft', 'subnautica', 'hurtworld', 'miscreated', 'deadside', 'sunkenland'] },
  { id: 'fps', label: 'FPS / Shooter', keywords: ['shooter', 'fps', 'tactical', 'counter-strike', 'cs2', 'csgo', 'insurgency', 'squad', 'arma', 'hell let loose', 'post scriptum', 'rising storm', 'killing floor', 'left 4 dead', 'pavlov', 'ready or not', 'ground branch', 'tf2', 'team fortress', 'quake', 'unreal tournament', 'mordhau', 'chivalry'] },
  { id: 'sandbox', label: 'Sandbox / Building', keywords: ['sandbox', 'build', 'factory', 'factorio', 'satisfactory', 'space engineers', 'medieval engineers', 'eco', 'creativerse', 'minetest', 'terraria', 'starbound', 'core keeper', 'vintage story'] },
  { id: 'racing', label: 'Racing / Driving', keywords: ['racing', 'race', 'truck', 'driving', 'car', 'assetto', 'rfactor', 'kartkraft', 'wreckfest', 'beamng', 'automobilista', 'dirt', 'trackmania', 'euro truck', 'american truck', 'mudrunner', 'snowrunner', 'farming simulator'] },
  { id: 'rpg', label: 'RPG / Adventure', keywords: ['rpg', 'adventure', 'mmo', 'v rising', 'mount & blade', 'bannerlord', 'wurm', 'path of titans', 'myth of empires', 'dark and darker', 'nightingale'] },
  { id: 'coop', label: 'Co-op / Horror', keywords: ['co-op', 'coop', 'horror', 'phasmophobia', 'lethal company', 'content warning', 'devour', 'gtfo', 'deep rock', 'risk of rain', 'barotrauma', 'sven co-op', 'alien swarm', 'no more room'] },
  { id: 'military', label: 'Military / Sim', keywords: ['military', 'ww2', 'ww1', 'war', 'battlefield', 'day of defeat', 'day of infamy', 'red orchestra', 'beyond the wire', 'operation harsh'] },
  { id: 'dinosaur', label: 'Dinosaur', keywords: ['dinosaur', 'dino', 'isle', 'ark', 'pixark', 'beasts of bermuda', 'path of titans'] },
  { id: 'gmod', label: 'Garry\'s Mod', keywords: ['gmod', 'garry', 'prophunt', 'ttt', 'darkrp', 'murder', 'sandbox'] },
  { id: 'source', label: 'Source Engine', keywords: ['source', 'half-life', 'black mesa', 'synergy', 'fistful', 'nuclear dawn', 'brainbread', 'zombie panic', 'age of chivalry', 'pirates, vikings'] },
];

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

  // Generate a random server name
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
  const [serverType, setServerType] = useState('');
  const [serverVersion, setServerVersion] = useState('');
  const [serverDefaults, setServerDefaults] = useState(null);

  // Load server defaults from settings
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
            // Apply defaults
            if (defaults.memory_min_mb) {
              setMinRam(`${defaults.memory_min_mb}M`);
              // If parent provided a create-form setter, update those too (values expected in MB)
              try {
                if (typeof setCreateMinRam === 'function') setCreateMinRam(String(defaults.memory_min_mb));
              } catch (e) {}
            }
            if (defaults.memory_max_mb) {
              setMaxRam(`${defaults.memory_max_mb}M`);
              try {
                if (typeof setCreateMaxRam === 'function') setCreateMaxRam(String(defaults.memory_max_mb));
              } catch (e) {}
            }
            if (defaults.java_args) {
              setJavaOverride(defaults.java_args);
            }
          }
        }
      } catch (e) {
        console.error('Failed to load server defaults:', e);
      }
    }
    loadServerDefaults();
    return () => { cancelled = true; };
  }, [API, safeAuthHeaders]);

  const [templatesTab, setTemplatesTab] = useState('minecraft');
  const [steamGames, setSteamGames] = useState([]);
  const [steamGamesLoading, setSteamGamesLoading] = useState(false);
  const [steamGamesError, setSteamGamesError] = useState('');
  const [steamPage, setSteamPage] = useState(0);
  const [steamHasMore, setSteamHasMore] = useState(false);
  const [steamSelectedGame, setSteamSelectedGame] = useState(null);
  const [steamForm, setSteamForm] = useState({ name: '', hostPort: '', env: {} });
  const [steamSubmitting, setSteamSubmitting] = useState(false);
  const [steamInstallResult, setSteamInstallResult] = useState(null);
  const [steamSearchQuery, setSteamSearchQuery] = useState('');
  const [steamCategory, setSteamCategory] = useState('all');
  const [steamAllGames, setSteamAllGames] = useState([]);
  const [steamTotalCount, setSteamTotalCount] = useState(0);

  
  useEffect(() => {
    let cancelled = false;
    async function loadAllSteamGames() {
      setSteamGamesLoading(true);
      setSteamGamesError('');
      try {
        const response = await fetch(`${API}/steam/games?include_all=true`, { headers: safeAuthHeaders() });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const message = data?.detail || `HTTP ${response.status}`;
          throw new Error(message);
        }
        if (!cancelled) {
          const rawGames = Array.isArray(data?.games) ? data.games : [];
          setSteamAllGames(rawGames);
          setSteamTotalCount(rawGames.length);
        }
      } catch (error) {
        if (!cancelled) {
          setSteamAllGames([]);
          setSteamGamesError(String(error?.message || error));
        }
      } finally {
        if (!cancelled) {
          setSteamGamesLoading(false);
        }
      }
    }
    loadAllSteamGames();
    return () => {
      cancelled = true;
    };
  }, [API, safeAuthHeaders]);

  
  const filteredSteamGames = useMemo(() => {
    let games = steamAllGames;
    
    
    if (steamCategory !== 'all') {
      const category = STEAM_CATEGORIES.find(c => c.id === steamCategory);
      if (category && category.keywords.length > 0) {
        games = games.filter(game => {
          const searchText = `${game.name || ''} ${game.summary || ''} ${game.slug || ''}`.toLowerCase();
          return category.keywords.some(kw => searchText.includes(kw.toLowerCase()));
        });
      }
    }
    
    
    if (steamSearchQuery.trim()) {
      const query = steamSearchQuery.toLowerCase().trim();
      games = games.filter(game => {
        const searchText = `${game.name || ''} ${game.summary || ''} ${game.slug || ''}`.toLowerCase();
        return searchText.includes(query);
      });
    }
    
    return games;
  }, [steamAllGames, steamSearchQuery, steamCategory]);

  
  useEffect(() => {
    const startIdx = steamPage * STEAM_PER_PAGE;
    const endIdx = startIdx + STEAM_PER_PAGE;
    const paginatedGames = filteredSteamGames.slice(startIdx, endIdx);
    setSteamGames(paginatedGames);
    setSteamHasMore(endIdx < filteredSteamGames.length);
  }, [filteredSteamGames, steamPage]);

  
  useEffect(() => {
    setSteamPage(0);
  }, [steamSearchQuery, steamCategory]);

  const goToPreviousSteamPage = () => {
    setSteamPage((prev) => (prev > 0 ? prev - 1 : 0));
  };

  const goToNextSteamPage = () => {
    if (steamHasMore) {
      setSteamPage((prev) => prev + 1);
    }
  };

  const randomSuffix = () => Math.random().toString(36).slice(2, 6);

  function openSteamGameInstaller(game) {
    if (!game) {
      setSteamSelectedGame(null);
      setSteamInstallResult(null);
      setSteamForm({ name: '', hostPort: '', env: {} });
      return;
    }
    const baseName = game.default_name || game.slug || 'steam';
    const envDefaults = {};
    if (game.env && typeof game.env === 'object') {
      Object.entries(game.env).forEach(([key, value]) => {
        envDefaults[key] = value === undefined || value === null ? '' : String(value);
      });
    }
    setSteamSelectedGame(game);
    setSteamForm({
      name: `${baseName}-${randomSuffix()}`,
      hostPort: '',
      env: envDefaults,
    });
    setSteamInstallResult(null);
  }

  function updateSteamEnv(key, value) {
    setSteamForm((prev) => ({
      ...prev,
      env: { ...prev.env, [key]: value },
    }));
  }

  function updateSteamField(field, value) {
    setSteamForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submitSteamInstall(e) {
    e.preventDefault();
    if (!steamSelectedGame) return;
    const trimmedName = (steamForm.name || '').trim();
    if (!trimmedName) {
      setSteamInstallResult({ ok: false, message: 'Server name is required.' });
      return;
    }

    setSteamSubmitting(true);
    setSteamInstallResult(null);

    try {
      const payload = {
        game: steamSelectedGame.slug,
        name: trimmedName,
      };

      const hostPortValue = (steamForm.hostPort || '').trim();
      if (hostPortValue) {
        const parsed = Number(hostPortValue);
        if (!Number.isInteger(parsed) || parsed <= 0 || parsed > 65535) {
          throw new Error('Host port must be a number between 1 and 65535.');
        }
        payload.host_port = parsed;
      }

      const envPayload = {};
      Object.entries(steamForm.env || {}).forEach(([key, value]) => {
        if (value === undefined || value === null) return;
        envPayload[key] = String(value);
      });
      if (Object.keys(envPayload).length > 0) {
        payload.env = envPayload;
      }

      const response = await fetch(`${API}/steam/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...safeAuthHeaders() },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data?.detail || `HTTP ${response.status}`;
        throw new Error(detail);
      }

      setSteamInstallResult({ ok: true, data });
    } catch (error) {
      setSteamInstallResult({ ok: false, message: String(error?.message || error) });
    } finally {
      setSteamSubmitting(false);
    }
  }

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
        if (!controller.signal.aborted && d?.port) {
          setCreateHostPort(String(d.port));
        }
      } catch {}
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
        const message = data?.detail || `HTTP ${response.status}`;
        setCatalogError(message);
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

  async function openInstallFromCatalog(pack, options = {}) {
    const {
      providerOverride,
      versionOverride,
      recommendedRam,
      suggestedName,
    } = options || {};

    if (suggestedName) {
      setServerName(suggestedName);
    }
    if (recommendedRam && recommendedRam.min) {
      setMinRam(recommendedRam.min);
    }
    if (recommendedRam && recommendedRam.max) {
      setMaxRam(recommendedRam.max);
    }

    setInstallPack(pack);
    setInstallOpen(true);
    setInstallEvents([]);
    setInstallWorking(false);
    try {
      const chosenProvider = providerOverride || provider || 'modrinth';
      setInstallProvider(chosenProvider);
      const packIdentifier = pack.id || pack.slug || pack.project_id || pack.projectSlug;
      if (!packIdentifier) {
        throw new Error('Missing pack identifier');
      }
      const response = await fetch(
        `${API}/catalog/${chosenProvider}/packs/${encodeURIComponent(String(packIdentifier))}/versions`,
        { headers: safeAuthHeaders() }
      );
      const data = await response.json().catch(() => ({}));
      const versions = Array.isArray(data?.versions) ? data.versions : [];
      setInstallVersions(versions);
      if (versionOverride) {
        const match = versions.find(v => String(v.id) === String(versionOverride));
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
      if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
      }
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
        } catch {
          
        }
      };
      es.onerror = () => {
        try {
          es.close();
        } catch {
          
        }
        setInstallWorking(false);
      };
    } catch (error) {
      setInstallEvents(prev => [...prev, { type: 'error', message: String(error.message || error) }]);
      setInstallWorking(false);
    }
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div>
        <h1 className="text-3xl font-bold flex items-center gap-3">
          <FaLayerGroup className="text-brand-500" /> <span className="gradient-text-brand">{t('templates.title')}</span>
        </h1>
        <p className="text-white/70 mt-2">{t('templates.description')}</p>
      </div>

      {/* Tab switcher: Minecraft vs Steam (other games) */}
      <div className="bg-white/5 border border-white/10 rounded-lg p-1 flex w-full md:w-fit">
        <button
          onClick={() => setTemplatesTab('minecraft')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${templatesTab === 'minecraft' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}`}
        >Minecraft</button>
        <button
          onClick={() => setTemplatesTab('steam')}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${templatesTab === 'steam' ? 'bg-brand-500 text-white' : 'text-white/70 hover:text-white hover:bg-white/10'}`}
        >{t('templates.steamGames')}</button>
      </div>

      {templatesTab === 'minecraft' ? (
        <>
          <div className="bg-white/5 border border-white/10 rounded-lg p-6">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-4">
              <div>
                <h3 className="text-lg font-semibold flex items-center gap-2">
                  <FaPlusCircle /> {t('templates.createNewServer')}
                </h3>
                <p className="text-sm text-white/60">{t('templates.createServerDescription')}</p>
              </div>
            </div>
            <form onSubmit={(e) => { if (onCreateServer) { onCreateServer(e); } else { e.preventDefault(); } }} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">{t('servers.serverName')}</label>
                  <input
                    type="text"
                    value={createName}
                    onChange={(e) => setCreateName(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white placeholder-white/50"
                    placeholder={t('templates.enterServerName')}
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">Server Type</label>
                  <select
                    value={createSelectedType}
                    onChange={(e) => setCreateSelectedType(e.target.value)}
                    className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded text-white"
                  >
                    {(types || []).map((t) => (
                      <option key={t} value={t} style={{ backgroundColor: '#1f2937' }}>{t}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">Version</label>
                  <select
                    value={createVersion}
                    onChange={(e) => setCreateVersion(e.target.value)}
                    className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded text-white"
                  >
                    {(versionsData?.versions || []).map((v) => (
                      <option key={v} value={v} style={{ backgroundColor: '#1f2937' }}>{v}</option>
                    ))}
                  </select>
                </div>
              </div>

              {SERVER_TYPES_WITH_LOADER.includes(createSelectedType) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-white/70 mb-2">Loader Version</label>
                    <select
                      value={createLoaderVersion}
                      onChange={(e) => setCreateLoaderVersion(e.target.value)}
                      className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded text-white"
                    >
                      {(createLoaderVersionsData?.loader_versions || []).map((lv) => (
                        <option key={lv} value={lv} style={{ backgroundColor: '#1f2937' }}>{lv}</option>
                      ))}
                    </select>
                  </div>
                  {createSelectedType === 'fabric' && (
                  <div>
                    <label className="block text-sm font-medium text-white/70 mb-2">Installer Version</label>
                    {Array.isArray(createLoaderVersionsData?.installer_versions) && createLoaderVersionsData.installer_versions.length > 0 ? (
                      <select
                        value={createInstallerVersion}
                        onChange={(e) => setCreateInstallerVersion(e.target.value)}
                        className="w-full px-3 py-2 bg-white/10 border border-white/20 rounded text-white"
                      >
                        {createLoaderVersionsData.installer_versions.map((iv) => (
                          <option key={iv} value={iv} style={{ backgroundColor: '#1f2937' }}>{iv}</option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={createInstallerVersion}
                        onChange={(e) => setCreateInstallerVersion(e.target.value)}
                        className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white placeholder-white/50"
                        placeholder="e.g., 1.0.1"
                      />
                    )}
                    <div className="text-xs text-white/40 mt-1">
                      {createLoaderVersionsData?.latest_installer_version ? (
                        <button type="button" className="underline" onClick={() => setCreateInstallerVersion(createLoaderVersionsData.latest_installer_version)}>
                          Use latest: {createLoaderVersionsData.latest_installer_version}
                        </button>
                      ) : null}
                    </div>
                  </div>
                  )}
                </div>
              )}

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">Host Port</label>
                  <input
                    type="number"
                    value={createHostPort}
                    onChange={(e) => setCreateHostPort(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white placeholder-white/50"
                    placeholder="25565"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">Min RAM (MB)</label>
                  <input
                    type="number"
                    value={createMinRam}
                    onChange={(e) => setCreateMinRam(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-white/70 mb-2">Max RAM (MB)</label>
                  <input
                    type="number"
                    value={createMaxRam}
                    onChange={(e) => setCreateMaxRam(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded text-white"
                  />
                </div>
              </div>

              <button
                type="submit"
                className="bg-brand-500 hover:bg-brand-600 px-6 py-3 rounded-lg text-white font-medium flex items-center gap-2"
              >
                <FaPlusCircle /> Create Server
              </button>
            </form>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-lg p-6">
            <h3 className="text-lg font-semibold mb-4">Import Local Server Pack (.zip)</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-white/70 mb-1">Server Name</label>
                <div className="flex gap-2">
                  <input
                    value={serverName}
                    onChange={e => setServerName(e.target.value)}
                    className="flex-1 rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                  />
                  <button
                    type="button"
                    onClick={() => setServerName(generateRandomName())}
                    className="px-3 py-2 rounded bg-white/10 hover:bg-white/20 text-white/70 hover:text-white transition-colors"
                    title="Generate random name"
                  >
                    <FaDice />
                  </button>
                </div>
              </div>
              <div>
                <label className="block text-sm text-white/70 mb-1">Host Port (optional)</label>
                <input
                  value={hostPort}
                  onChange={e => setHostPort(e.target.value)}
                  className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                  placeholder="e.g. 25565"
                />
              </div>
              <div className="md:col-span-2">
                <label className="block text-sm text-white/70 mb-1">Select ZIP file</label>
                <input
                  type="file"
                  accept=".zip"
                  onChange={event => setZipFile(event.target.files && event.target.files[0] ? event.target.files[0] : null)}
                  className="w-full text-sm text-white"
                />
              </div>
              <div>
                <label className="block text-sm text-white/70 mb-1">Min RAM</label>
                <input
                  value={minRam}
                  onChange={e => setMinRam(e.target.value)}
                  onBlur={() => {
                    const value = normalizeRamInput(minRam);
                    if (value) setMinRam(value);
                  }}
                  className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                  aria-describedby="zip-min-ram-help"
                />
                <div id="zip-min-ram-help" className="text-[11px] text-white/50 mt-1">Formats: 2048M, 2G, 2048.</div>
              </div>
              <div>
                <label className="block text-sm text-white/70 mb-1">Max RAM</label>
                <input
                  value={maxRam}
                  onChange={e => setMaxRam(e.target.value)}
                  onBlur={() => {
                    const value = normalizeRamInput(maxRam);
                    if (value) setMaxRam(value);
                  }}
                  className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                  aria-describedby="zip-max-ram-help"
                />
                <div id="zip-max-ram-help" className="text-[11px] text-white/50 mt-1">Formats: 4096M, 4G, 4096.</div>
              </div>
              <div className="md:col-span-2 flex items-center gap-3">
                <button
                  disabled={busy || !zipFile}
                  onClick={async () => {
                    setBusy(true);
                    setMsg('');
                    try {
                      const normMin = normalizeRamInput(minRam);
                      const normMax = normalizeRamInput(maxRam);
                      if (!normMin || !normMax) {
                        setMsg('Invalid RAM values. Examples: 2048M, 2G, 2048');
                        setBusy(false);
                        return;
                      }
                      const formData = new FormData();
                      formData.append('server_name', serverName);
                      if (hostPort) formData.append('host_port', hostPort);
                      formData.append('min_ram', normMin);
                      formData.append('max_ram', normMax);
                      if (javaOverride) formData.append('java_version_override', javaOverride);
                      if (serverType) formData.append('server_type', serverType);
                      if (serverVersion) formData.append('server_version', serverVersion);
                      if (zipFile) formData.append('file', zipFile);
                      const response = await fetch(`${API}/modpacks/import-upload`, { method: 'POST', headers: safeAuthHeaders(), body: formData });
                      const data = await response.json().catch(() => ({}));
                      if (!response.ok) {
                        throw new Error(data?.detail || `HTTP ${response.status}`);
                      }
                      setMsg('Server pack uploaded and container started. Go to Servers to see it.');
                    } catch (error) {
                      setMsg(`Error: ${error.message || error}`);
                    } finally {
                      setBusy(false);
                    }
                  }}
                  className="bg-brand-500 hover:bg-brand-600 disabled:opacity-50 px-4 py-2 rounded flex items-center gap-2"
                  aria-busy={busy}
                  aria-live="polite"
                >
                  {busy && (
                    <span
                      className="animate-spin inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full"
                      aria-hidden="true"
                    ></span>
                  )}
                  {busy ? 'Uploading…' : 'Import ZIP'}
                </button>
                {msg && <div className="text-sm text-white/70">{msg}</div>}
              </div>
            </div>
          </div>

          <div className="bg-white/5 border border-white/10 rounded-lg p-6 space-y-4">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold">Search Modpacks</h3>
                <p className="text-sm text-white/60">Find packs from Modrinth or CurseForge.</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-4">
              <select
                className="rounded bg-white/10 border border-white/20 px-3 py-2 text-white"
                value={provider}
                onChange={e => setProvider(e.target.value)}
                style={{ backgroundColor: '#1f2937' }}
              >
                {providers.map(p => (
                  <option
                    key={p.id}
                    value={p.id}
                    disabled={p.requires_key && !p.configured}
                    style={{ backgroundColor: '#1f2937' }}
                  >
                    {p.name}
                    {p.requires_key && !p.configured ? ' (configure in Settings)' : ''}
                  </option>
                ))}
              </select>
              <input
                className="rounded bg-white/5 border border-white/10 px-3 py-2 text-white placeholder-white/50"
                placeholder="Type modpack name (e.g. Beyond Cosmo)"
                value={catalogQuery}
                onChange={e => setCatalogQuery(e.target.value)}
              />
              <input
                className="rounded bg-white/5 border border-white/10 px-3 py-2 text-white placeholder-white/50"
                placeholder="MC Version (e.g. 1.20.4)"
                value={catalogMC}
                onChange={e => setCatalogMC(e.target.value)}
              />
              <select
                className="rounded bg-white/10 border border-white/20 px-3 py-2 text-white"
                value={catalogLoader}
                onChange={e => setCatalogLoader(e.target.value)}
                style={{ backgroundColor: '#1f2937' }}
              >
                <option value="" style={{ backgroundColor: '#1f2937' }}>
                  Any Loader
                </option>
                <option value="fabric" style={{ backgroundColor: '#1f2937' }}>
                  Fabric
                </option>
                <option value="forge" style={{ backgroundColor: '#1f2937' }}>
                  Forge
                </option>
                <option value="neoforge" style={{ backgroundColor: '#1f2937' }}>
                  NeoForge
                </option>
              </select>
              <div className="md:col-span-4 flex items-center gap-2">
                <button onClick={() => { setCatalogPage(1); searchCatalog(); }} className="bg-brand-500 hover:bg-brand-600 px-3 py-2 rounded">
                  Search
                </button>
                {catalogLoading && <div className="text-sm text-white/60">Loading…</div>}
                {catalogError && <div className="text-sm text-red-400">{catalogError}</div>}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {catalogResults.map((pack, idx) => (
                <div key={pack.id || pack.slug || idx} className="bg-white/5 border border-white/10 rounded-lg p-4 flex flex-col">
                  <div className="flex items-center gap-3 mb-2">
                    {pack.icon_url ? (
                      <img src={pack.icon_url} alt="" className="w-8 h-8 rounded" />
                    ) : (
                      <div className="w-8 h-8 bg-white/10 rounded" />
                    )}
                    <div>
                      <div className="font-semibold">{pack.name}</div>
                      <div className="text-xs text-white/60">{(pack.categories || []).slice(0, 3).join(' · ')}</div>
                    </div>
                  </div>
                  <div className="text-sm text-white/70 line-clamp-2">{pack.description}</div>
                  <div className="mt-2 flex items-center gap-3 text-xs text-white/60">
                    {typeof pack.downloads === 'number' && <span>⬇ {Intl.NumberFormat().format(pack.downloads)}</span>}
                    {pack.updated && <span>Updated {new Date(pack.updated).toLocaleDateString()}</span>}
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <button onClick={() => openInstallFromCatalog(pack)} className="bg-brand-500 hover:bg-brand-600 px-3 py-1.5 rounded text-sm">
                      Install
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {installOpen && (
            <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
              <div className="bg-ink border border-white/10 rounded-lg p-6 w-full max-w-2xl">
                <div className="flex items-center justify-between mb-4">
                  <div className="text-lg font-semibold">Install Modpack{installPack?.name ? `: ${installPack.name}` : ''}</div>
                  <button
                    onClick={() => {
                      setInstallOpen(false);
                      setInstallPack(null);
                    }}
                    className="text-white/60 hover:text-white"
                  >
                    Close
                  </button>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
                  <div>
                    <label className="block text-xs text-white/60 mb-1">Version</label>
                    <select
                      className="w-full rounded bg-white/10 border border-white/20 px-3 py-2 text-white"
                      value={installVersionId}
                      onChange={e => setInstallVersionId(e.target.value)}
                      style={{ backgroundColor: '#1f2937' }}
                    >
                      {installVersions.map(version => (
                        <option key={version.id} value={version.id} style={{ backgroundColor: '#1f2937' }}>
                          {version.name || version.version_number}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-white/60 mb-1">Server Name</label>
                    <div className="flex gap-2">
                      <input
                        className="flex-1 rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                        value={serverName}
                        onChange={e => setServerName(e.target.value)}
                      />
                      <button
                        type="button"
                        onClick={() => setServerName(generateRandomName())}
                        className="px-3 py-2 rounded bg-white/10 hover:bg-white/20 text-white/70 hover:text-white transition-colors"
                        title="Generate random name"
                      >
                        <FaDice />
                      </button>
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-white/60 mb-1">Host Port (optional)</label>
                    <input
                      className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                      value={hostPort}
                      onChange={e => setHostPort(e.target.value)}
                      placeholder="25565"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-white/60 mb-1">Min RAM</label>
                      <input
                        className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                        value={minRam}
                        onChange={e => setMinRam(e.target.value)}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-white/60 mb-1">Max RAM</label>
                      <input
                        className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                        value={maxRam}
                        onChange={e => setMaxRam(e.target.value)}
                      />
                    </div>
                  </div>
                  <div className="md:col-span-2 flex items-center gap-2 mt-2">
                    <button
                      disabled={installWorking}
                      onClick={submitInstall}
                      className="bg-brand-500 hover:bg-brand-600 disabled:opacity-50 px-4 py-2 rounded"
                    >
                      {installWorking ? 'Installing…' : 'Start Install'}
                    </button>
                    <div className="text-sm text-white/70">{installPack?.provider || provider}</div>
                  </div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded p-3 h-40 overflow-auto text-sm">
                  {installEvents.length === 0 ? (
                    <div className="text-white/50">No events yet…</div>
                  ) : (
                    <ul className="space-y-1">
                      {installEvents.map((event, index) => {
                        let text = '';
                        if (typeof event?.message === 'string') {
                          text = event.message;
                        } else if (event?.message) {
                          try {
                            text = JSON.stringify(event.message);
                          } catch {
                            text = String(event.message);
                          }
                        } else if (event?.step) {
                          const pct = typeof event.progress === 'number' ? ` (${event.progress}%)` : '';
                          text = `${event.step}${pct}`;
                        } else {
                          try {
                            text = JSON.stringify(event);
                          } catch {
                            text = String(event);
                          }
                        }
                        return (
                          <li key={index} className="flex items-start gap-2">
                            <span
                              className="w-2 h-2 rounded-full mt-2"
                              style={{ background: event.type === 'error' ? '#f87171' : event.type === 'done' ? '#34d399' : '#a78bfa' }}
                            ></span>
                            <span>{text}</span>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="bg-white/5 border border-white/10 rounded-lg p-6 space-y-6">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h3 className="text-lg font-semibold">Steam & Other Dedicated Servers</h3>
              <p className="text-sm text-white/60">
                Deploy {steamTotalCount > 0 ? `${steamTotalCount}+` : ''} curated game servers with one click. 
                {filteredSteamGames.length !== steamTotalCount && filteredSteamGames.length > 0 && (
                  <span className="ml-1 text-brand-300">Showing {filteredSteamGames.length} matches.</span>
                )}
              </p>
            </div>
            <span className="text-xs uppercase tracking-wide bg-brand-500/15 text-brand-200 px-3 py-1 rounded">Beta</span>
          </div>

          {/* Search and Category Filter */}
          <div className="flex flex-col md:flex-row gap-3">
            <div className="flex-1">
              <input
                type="text"
                placeholder="Search games... (e.g. Valheim, Rust, ARK)"
                value={steamSearchQuery}
                onChange={(e) => setSteamSearchQuery(e.target.value)}
                className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:border-brand-400/50 focus:outline-none transition"
              />
            </div>
            <div className="flex flex-wrap gap-2">
              {STEAM_CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  type="button"
                  onClick={() => setSteamCategory(cat.id)}
                  className={`px-3 py-2 text-xs rounded-lg border transition-all ${
                    steamCategory === cat.id
                      ? 'bg-brand-500 border-brand-400 text-white'
                      : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10 hover:text-white'
                  }`}
                >
                  {cat.label}
                </button>
              ))}
            </div>
          </div>

          {steamGamesError ? (
            <div className="bg-red-500/10 border border-red-400/30 text-red-200 rounded-lg px-4 py-3 text-sm">
              {steamGamesError}
            </div>
          ) : null}

          {steamGamesLoading ? (
            <div className="text-sm text-white/60">Loading Steam catalog…</div>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                {steamGames.map((game) => {
                  const isSelected = steamSelectedGame?.slug === game.slug;
                  return (
                    <div
                      key={game.slug || game.name}
                      className={`bg-white/5 border rounded-lg p-4 space-y-2 transition-all cursor-pointer hover:border-brand-400/40 hover:bg-brand-500/5 ${
                        isSelected ? 'border-brand-400/60 bg-brand-500/10 shadow-lg shadow-brand-500/20 ring-1 ring-brand-400/30' : 'border-white/10'
                      }`}
                      onClick={() => openSteamGameInstaller(game)}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="text-white font-semibold text-sm truncate" title={game.name || game.slug}>
                            {game.name || game.slug}
                          </div>
                        </div>
                        {isSelected && (
                          <span className="flex-shrink-0 w-2 h-2 bg-brand-400 rounded-full mt-1.5"></span>
                        )}
                      </div>
                      <div className="text-xs text-white/50 line-clamp-2 min-h-[2.5rem]">
                        {game.summary || game.notes || 'Dedicated server template.'}
                      </div>
                      <div className="flex items-center justify-between gap-2 pt-1">
                        <div className="text-[10px] text-white/40 truncate flex-1">
                          {(game.ports || []).slice(0, 2).map((p) => `${p.container}/${(p.protocol || 'tcp').toUpperCase()}`).join(', ')}
                          {(game.ports || []).length > 2 && ` +${game.ports.length - 2}`}
                        </div>
                        <span className="text-[10px] bg-white/10 text-white/50 px-1.5 py-0.5 rounded flex-shrink-0">Linux</span>
                      </div>
                    </div>
                  );
                })}
                {steamGames.length === 0 && !steamGamesError && !steamGamesLoading ? (
                  <div className="col-span-full bg-white/5 border border-white/10 rounded-lg p-6 text-sm text-white/60 text-center">
                    {steamSearchQuery || steamCategory !== 'all' 
                      ? 'No games match your search. Try different keywords or select "All Games".'
                      : 'No Steam templates available yet. Check back soon.'}
                  </div>
                ) : null}
              </div>
              <div className="flex items-center justify-between mt-4">
                <button
                  type="button"
                  onClick={goToPreviousSteamPage}
                  className="px-3 py-1.5 text-xs rounded border border-white/10 bg-white/5 text-white/70 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white/10 transition"
                  disabled={steamPage === 0 || steamGamesLoading}
                >
                  Previous
                </button>
                <span className="text-xs text-white/60">
                  Page {steamPage + 1} of {Math.max(1, Math.ceil(filteredSteamGames.length / STEAM_PER_PAGE))}
                  {filteredSteamGames.length > 0 && (
                    <span className="ml-2 text-white/40">({filteredSteamGames.length} games)</span>
                  )}
                </span>
                <button
                  type="button"
                  onClick={goToNextSteamPage}
                  className="px-3 py-1.5 text-xs rounded border border-white/10 bg-white/5 text-white/70 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white/10 transition"
                  disabled={!steamHasMore || steamGamesLoading}
                >
                  Next
                </button>
              </div>
            </>
          )}

          {steamSelectedGame ? (
            <div className="bg-black/20 border border-white/10 rounded-lg p-5 space-y-4">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h4 className="text-lg font-semibold text-white">Deploy {steamSelectedGame.name || steamSelectedGame.slug}</h4>
                  <p className="text-sm text-white/60 mt-1 max-w-2xl">Customize the container name, optional host port, and credentials before provisioning.</p>
                </div>
                <button
                  type="button"
                  onClick={() => openSteamGameInstaller(null)}
                  className="text-xs text-white/60 hover:text-white transition-colors"
                >
                  Clear selection
                </button>
              </div>

              {steamInstallResult ? (
                <div
                  className={`rounded-lg border px-4 py-3 text-sm ${
                    steamInstallResult.ok
                      ? 'bg-green-500/10 border-green-400/30 text-green-100'
                      : 'bg-red-500/10 border-red-400/30 text-red-100'
                  }`}
                >
                  <div className="font-semibold">
                    {steamInstallResult.ok ? 'Install request queued' : 'Install failed'}
                  </div>
                  <div className="mt-1 text-xs text-white/80">
                    {steamInstallResult.ok
                      ? 'Docker is provisioning the container now. It will appear under My Servers shortly.'
                      : steamInstallResult.message}
                  </div>
                  {steamInstallResult.ok && steamInstallResult.data?.ports ? (
                    <div className="mt-3 text-xs text-white/80 space-y-1">
                      <div className="font-semibold text-white">Assigned ports</div>
                      {Object.entries(steamInstallResult.data.ports).map(([key, host]) => (
                        <div key={key} className="flex justify-between gap-4">
                          <span className="text-white/60">{key}</span>
                          <span className="text-white">{host}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {steamInstallResult.ok && steamInstallResult.data?.env ? (
                    <div className="mt-3 text-xs text-white/80 space-y-1">
                      <div className="font-semibold text-white">Saved credentials</div>
                      {Object.entries(steamInstallResult.data.env).map(([key, value]) => (
                        <div key={key} className="flex justify-between gap-4">
                          <span className="text-white/60">{key}</span>
                          <span className="text-white">{value}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {steamInstallResult.ok && steamInstallResult.data?.data_path ? (
                    <div className="mt-3 text-xs text-white/60">Data directory: {steamInstallResult.data.data_path}</div>
                  ) : null}
                </div>
              ) : null}

              <form onSubmit={submitSteamInstall} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-white/60 mb-1">Server name</label>
                    <div className="flex gap-2">
                      <input
                        className="flex-1 rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                        value={steamForm.name}
                        onChange={(e) => updateSteamField('name', e.target.value)}
                        placeholder={`${steamSelectedGame.default_name || steamSelectedGame.slug}-server`}
                        required
                      />
                      <button
                        type="button"
                        onClick={() => updateSteamField('name', generateRandomName())}
                        className="px-3 py-2 rounded bg-white/10 hover:bg-white/20 text-white/70 hover:text-white transition-colors"
                        title="Generate random name"
                      >
                        <FaDice />
                      </button>
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs text-white/60 mb-1">Host port (optional)</label>
                    <input
                      className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                      value={steamForm.hostPort}
                      onChange={(e) => updateSteamField('hostPort', e.target.value.replace(/[^0-9]/g, ''))}
                      placeholder="Auto-assign"
                      inputMode="numeric"
                    />
                  </div>
                </div>

                <div className="space-y-3">
                  <div className="text-xs uppercase tracking-wide text-white/50">Environment overrides</div>
                  {steamSelectedGame?.slug === 'tmodloader' ? (
                    <div className="bg-white/5 border border-white/10 rounded-lg p-3 space-y-3">
                      <div className="text-xs text-white/60 uppercase tracking-wide">Terraria world setup</div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-1">
                          <label className="block text-xs text-white/60">World name</label>
                          <input
                            className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                            value={steamForm.env?.WORLD_NAME ?? ''}
                            onChange={(e) => updateSteamEnv('WORLD_NAME', e.target.value)}
                            placeholder="Dedicated"
                          />
                        </div>
                        <div className="space-y-1">
                          <label className="block text-xs text-white/60">World filename</label>
                          <input
                            className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                            value={steamForm.env?.WORLD_FILENAME ?? ''}
                            onChange={(e) => updateSteamEnv('WORLD_FILENAME', e.target.value)}
                            placeholder="Dedicated.wld"
                          />
                          <div className="text-[11px] text-white/40">Ends with .wld and must exist or be generated.</div>
                        </div>
                        <div className="space-y-1">
                          <label className="block text-xs text-white/60">World size</label>
                          <select
                            className="w-full rounded bg-white/10 border border-white/20 px-3 py-2 text-white"
                            value={steamForm.env?.WORLD_SIZE === undefined || steamForm.env.WORLD_SIZE === null ? '3' : String(steamForm.env.WORLD_SIZE)}
                            onChange={(e) => updateSteamEnv('WORLD_SIZE', e.target.value)}
                            style={{ backgroundColor: '#1f2937' }}
                          >
                            {TMOD_WORLD_SIZE_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value} style={{ backgroundColor: '#1f2937' }}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="space-y-1">
                          <label className="block text-xs text-white/60">World difficulty</label>
                          <select
                            className="w-full rounded bg-white/10 border border-white/20 px-3 py-2 text-white"
                            value={steamForm.env?.WORLD_DIFFICULTY === undefined || steamForm.env.WORLD_DIFFICULTY === null ? '1' : String(steamForm.env.WORLD_DIFFICULTY)}
                            onChange={(e) => updateSteamEnv('WORLD_DIFFICULTY', e.target.value)}
                            style={{ backgroundColor: '#1f2937' }}
                          >
                            {TMOD_WORLD_DIFFICULTY_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value} style={{ backgroundColor: '#1f2937' }}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </div>
                        <div className="space-y-1">
                          <label className="block text-xs text-white/60">World seed (optional)</label>
                          <input
                            className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                            value={steamForm.env?.WORLD_SEED ?? ''}
                            onChange={(e) => updateSteamEnv('WORLD_SEED', e.target.value)}
                            placeholder="Random"
                          />
                        </div>
                      </div>
                      <div className="text-[11px] text-white/40">Adjust size and difficulty before first launch to generate the desired world.</div>
                    </div>
                  ) : null}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    {Object.keys(steamForm.env || {}).length === 0 ? (
                      <div className="text-xs text-white/50">No environment variables exposed for this template.</div>
                    ) : null}
                    {Object.entries(steamForm.env || {}).map(([key, value]) => {
                      if (steamSelectedGame?.slug === 'tmodloader' && TMOD_WORLD_ENV_KEY_SET.has(key)) {
                        return null;
                      }
                      const isSecret = key.toLowerCase().includes('password') || key.toLowerCase().includes('token');
                      return (
                        <div key={key} className="space-y-1">
                          <label className="block text-xs text-white/60">{key}</label>
                          <input
                            type={isSecret ? 'password' : 'text'}
                            className="w-full rounded bg-white/5 border border-white/10 px-3 py-2 text-white"
                            value={value ?? ''}
                            onChange={(e) => updateSteamEnv(key, e.target.value)}
                          />
                        </div>
                      );
                    })}
                  </div>
                  <div className="text-xs text-white/40">Leave fields untouched to use the recommended defaults. Password fields are generated automatically if left as placeholders.</div>
                </div>

                <div className="flex items-center gap-3">
                  <button
                    type="submit"
                    disabled={steamSubmitting}
                    className="inline-flex items-center gap-2 rounded-md bg-brand-500 hover:bg-brand-600 disabled:opacity-60 px-4 py-2 text-sm font-medium text-white transition-colors"
                  >
                    {steamSubmitting ? 'Provisioning…' : 'Provision Server'}
                  </button>
                  <div className="text-xs text-white/50">Provisioning may take up to a minute depending on download size.</div>
                </div>
              </form>
            </div>
          ) : (
            <div className="bg-black/20 border border-white/10 rounded-lg p-5 text-sm text-white/60">
              Select a game above to review default settings and deploy. The controller assigns open host ports automatically when none are provided.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
