import React, { useEffect, useState, useMemo } from 'react';
import { FaDownload, FaTrash, FaCube, FaSearch, FaTimes, FaSteam, FaBolt, FaExternalLinkAlt, FaCog, FaFolder, FaFire, FaGlobe, FaExchangeAlt } from 'react-icons/fa';
import { API, getStoredToken } from '../../lib/api';

// Source display config
const SOURCE_INFO = {
    thunderstore: { label: 'Thunderstore', icon: FaBolt, color: 'text-blue-400', bg: 'bg-blue-500/20' },
    workshop:     { label: 'Steam Workshop', icon: FaSteam, color: 'text-blue-400', bg: 'bg-blue-500/20' },
    curseforge:   { label: 'CurseForge', icon: FaFire, color: 'text-orange-400', bg: 'bg-orange-500/20' },
    nexus:        { label: 'Nexus Mods', icon: FaGlobe, color: 'text-yellow-400', bg: 'bg-yellow-500/20' },
    modio:        { label: 'mod.io', icon: FaGlobe, color: 'text-green-400', bg: 'bg-green-500/20' },
};

// Games mapped to ALL their available mod sources (multi-source support)
const SUPPORTED_GAMES = {
    // ---- Games with multiple sources ----
    valheim:            { name: 'Valheim', sources: [
        { type: 'thunderstore', community: 'valheim' },
        { type: 'curseforge', slug: 'valheim', game_id: 68940 },
        { type: 'nexus', domain: 'valheim' },
        { type: 'workshop', appid: 892970 },
    ]},
    palworld:           { name: 'Palworld', sources: [
        { type: 'thunderstore', community: 'palworld' },
        { type: 'curseforge', slug: 'palworld', game_id: 85196 },
        { type: 'nexus', domain: 'palworld' },
    ]},
    '7_days_to_die':    { name: '7 Days to Die', sources: [
        { type: 'workshop', appid: 251570 },
        { type: 'curseforge', slug: '7_days_to_die', game_id: 7 },
        { type: 'nexus', domain: '7daystodie' },
    ]},
    sdtd:               { name: '7 Days to Die', sources: [
        { type: 'workshop', appid: 251570 },
        { type: 'curseforge', slug: 'sdtd', game_id: 7 },
        { type: 'nexus', domain: '7daystodie' },
    ]},
    rimworld:           { name: 'RimWorld', sources: [
        { type: 'workshop', appid: 294100 },
        { type: 'curseforge', slug: 'rimworld', game_id: 73492 },
        { type: 'nexus', domain: 'rimworld' },
    ]},
    vrising:            { name: 'V Rising', sources: [
        { type: 'thunderstore', community: 'v-rising' },
        { type: 'curseforge', slug: 'vrising', game_id: 78135 },
        { type: 'nexus', domain: 'vrising' },
    ]},
    conan_exiles:       { name: 'Conan Exiles', sources: [
        { type: 'workshop', appid: 440900 },
        { type: 'curseforge', slug: 'conan_exiles', game_id: 58498 },
        { type: 'nexus', domain: 'conanexiles' },
        { type: 'modio', game_id: 42 },
    ]},
    core_keeper:        { name: 'Core Keeper', sources: [
        { type: 'thunderstore', community: 'core-keeper' },
        { type: 'curseforge', slug: 'core_keeper', game_id: 79917 },
        { type: 'nexus', domain: 'corekeeper' },
    ]},
    satisfactory:       { name: 'Satisfactory', sources: [
        { type: 'curseforge', slug: 'satisfactory', game_id: 84368 },
        { type: 'nexus', domain: 'satisfactory' },
    ]},
    stardew_valley:     { name: 'Stardew Valley', sources: [
        { type: 'curseforge', slug: 'stardew_valley', game_id: 669 },
        { type: 'nexus', domain: 'stardewvalley' },
        { type: 'thunderstore', community: 'stardew-valley' },
    ]},
    lethal_company:     { name: 'Lethal Company', sources: [
        { type: 'thunderstore', community: 'lethal-company' },
        { type: 'nexus', domain: 'lethalcompany' },
        { type: 'curseforge', slug: 'lethal_company', game_id: 83671 },
    ]},
    among_us:           { name: 'Among Us', sources: [
        { type: 'thunderstore', community: 'among-us' },
        { type: 'curseforge', slug: 'among_us', game_id: 69761 },
        { type: 'nexus', domain: 'amongus' },
    ]},
    terraria:           { name: 'Terraria', sources: [
        { type: 'curseforge', slug: 'terraria', game_id: 431 },
        { type: 'nexus', domain: 'terraria' },
    ]},
    terraria_tmodloader:{ name: 'Terraria (tModLoader)', sources: [
        { type: 'workshop', appid: 1281930 },
        { type: 'curseforge', slug: 'terraria_tmodloader', game_id: 431 },
        { type: 'nexus', domain: 'terraria' },
    ]},
    tmodloader:         { name: 'Terraria (tModLoader)', sources: [
        { type: 'workshop', appid: 1281930 },
        { type: 'curseforge', slug: 'terraria_tmodloader', game_id: 431 },
    ]},
    rust:               { name: 'Rust', sources: [
        { type: 'workshop', appid: 252490 },
        { type: 'curseforge', slug: 'rust', game_id: 69162 },
        { type: 'nexus', domain: 'rust' },
    ]},
    project_zomboid:    { name: 'Project Zomboid', sources: [
        { type: 'workshop', appid: 108600 },
        { type: 'curseforge', slug: 'project_zomboid', game_id: 78135 },
        { type: 'nexus', domain: 'projectzomboid' },
    ]},
    dont_starve_together: { name: "Don't Starve Together", sources: [
        { type: 'workshop', appid: 322330 },
        { type: 'curseforge', slug: 'dont_starve_together', game_id: 4525 },
        { type: 'nexus', domain: 'dontstarvetogether' },
    ]},
    dayz:               { name: 'DayZ', sources: [
        { type: 'workshop', appid: 221100 },
        { type: 'curseforge', slug: 'dayz', game_id: 82002 },
        { type: 'nexus', domain: 'dayz' },
    ]},
    sons_of_the_forest: { name: 'Sons of the Forest', sources: [
        { type: 'thunderstore', community: 'sons-of-the-forest' },
        { type: 'curseforge', slug: 'sons_of_the_forest', game_id: 83879 },
        { type: 'nexus', domain: 'sonsoftheforest' },
    ]},
    enshrouded:         { name: 'Enshrouded', sources: [
        { type: 'thunderstore', community: 'enshrouded' },
        { type: 'curseforge', slug: 'enshrouded', game_id: 85767 },
        { type: 'nexus', domain: 'enshrouded' },
    ]},
    manor_lords:        { name: 'Manor Lords', sources: [
        { type: 'curseforge', slug: 'manor_lords', game_id: 85406 },
        { type: 'nexus', domain: 'manorlords' },
    ]},

    // ---- Nexus-primary games ----
    baldurs_gate_3:     { name: "Baldur's Gate 3", sources: [
        { type: 'nexus', domain: 'baldursgate3' },
        { type: 'curseforge', slug: 'baldurs_gate_3', game_id: 84299 },
    ]},
    bg3:                { name: "Baldur's Gate 3", sources: [
        { type: 'nexus', domain: 'baldursgate3' },
        { type: 'curseforge', slug: 'bg3', game_id: 84299 },
    ]},
    skyrim:             { name: 'Skyrim Special Edition', sources: [
        { type: 'nexus', domain: 'skyrimspecialedition' },
        { type: 'curseforge', slug: 'skyrim', game_id: 73492 },
    ]},
    fallout_4:          { name: 'Fallout 4', sources: [
        { type: 'nexus', domain: 'fallout4' },
        { type: 'curseforge', slug: 'fallout_4', game_id: 80122 },
    ]},
    starfield:          { name: 'Starfield', sources: [
        { type: 'nexus', domain: 'starfield' },
        { type: 'curseforge', slug: 'starfield', game_id: 83951 },
    ]},
    cyberpunk_2077:     { name: 'Cyberpunk 2077', sources: [
        { type: 'nexus', domain: 'cyberpunk2077' },
        { type: 'curseforge', slug: 'cyberpunk_2077', game_id: 78330 },
    ]},
    ark_survival_evolved: { name: 'ARK: Survival Evolved', sources: [
        { type: 'workshop', appid: 346110 },
        { type: 'nexus', domain: 'arksurvivalevolved' },
    ]},
    ark:                { name: 'ARK: Survival Evolved', sources: [
        { type: 'workshop', appid: 346110 },
        { type: 'nexus', domain: 'arksurvivalevolved' },
    ]},
    ark_survival_ascended: { name: 'ARK: Survival Ascended', sources: [
        { type: 'curseforge', slug: 'ark_survival_ascended', game_id: 84698 },
        { type: 'nexus', domain: 'arksurvivalascended' },
    ]},

    // ---- Workshop-only games ----
    gmod:               { name: "Garry's Mod", sources: [
        { type: 'workshop', appid: 4000 },
        { type: 'nexus', domain: 'garysmod' },
    ]},
    garrys_mod:         { name: "Garry's Mod", sources: [
        { type: 'workshop', appid: 4000 },
        { type: 'nexus', domain: 'garysmod' },
    ]},
    arma3:              { name: 'Arma 3', sources: [{ type: 'workshop', appid: 107410 }] },
    space_engineers:    { name: 'Space Engineers', sources: [{ type: 'workshop', appid: 244850 }] },
    cs2:                { name: 'Counter-Strike 2', sources: [{ type: 'workshop', appid: 730 }] },
    tf2:                { name: 'Team Fortress 2', sources: [{ type: 'workshop', appid: 440 }] },
    left4dead2:         { name: 'Left 4 Dead 2', sources: [{ type: 'workshop', appid: 550 }] },
    l4d2:               { name: 'Left 4 Dead 2', sources: [{ type: 'workshop', appid: 550 }] },
    barotrauma:         { name: 'Barotrauma', sources: [{ type: 'workshop', appid: 602960 }] },
    unturned:           { name: 'Unturned', sources: [
        { type: 'workshop', appid: 304930 },
        { type: 'curseforge', slug: 'unturned', game_id: 79744 },
    ]},
    stormworks:         { name: 'Stormworks', sources: [{ type: 'workshop', appid: 573090 }] },
    assetto_corsa:      { name: 'Assetto Corsa', sources: [{ type: 'workshop', appid: 244210 }] },
    factorio:           { name: 'Factorio', sources: [
        { type: 'workshop', appid: 427520 },
        { type: 'curseforge', slug: 'factorio', game_id: 79148 },
    ]},
    avorion:            { name: 'Avorion', sources: [{ type: 'workshop', appid: 445220 }] },
    eco:                { name: 'Eco', sources: [
        { type: 'workshop', appid: 382310 },
        { type: 'curseforge', slug: 'eco', game_id: 79501 },
        { type: 'modio', game_id: 6 },
    ]},

    // ---- Thunderstore-only games ----
    risk_of_rain_2:     { name: 'Risk of Rain 2', sources: [{ type: 'thunderstore', community: 'ror2' }] },
    sunkenland:         { name: 'Sunkenland', sources: [{ type: 'thunderstore', community: 'sunkenland' }] },
    content_warning:    { name: 'Content Warning', sources: [{ type: 'thunderstore', community: 'content-warning' }] },
    inscryption:        { name: 'Inscryption', sources: [{ type: 'thunderstore', community: 'inscryption' }] },
    gtfo:               { name: 'GTFO', sources: [{ type: 'thunderstore', community: 'gtfo' }] },
    dyson_sphere_program: { name: 'Dyson Sphere Program', sources: [
        { type: 'thunderstore', community: 'dyson-sphere-program' },
        { type: 'curseforge', slug: 'dyson_sphere_program', game_id: 82729 },
    ]},
    the_forest:         { name: 'The Forest', sources: [
        { type: 'thunderstore', community: 'the-forest' },
        { type: 'curseforge', slug: 'the_forest', game_id: 60028 },
        { type: 'nexus', domain: 'theforest' },
    ]},

    // ---- CurseForge-only games ----
    ksp:                { name: 'Kerbal Space Program', sources: [{ type: 'curseforge', slug: 'ksp', game_id: 4401 }] },
    kerbal_space_program: { name: 'Kerbal Space Program', sources: [{ type: 'curseforge', slug: 'ksp', game_id: 4401 }] },
    hogwarts_legacy:    { name: 'Hogwarts Legacy', sources: [
        { type: 'curseforge', slug: 'hogwarts_legacy', game_id: 80815 },
        { type: 'nexus', domain: 'hogwartslegacy' },
    ]},
    darkest_dungeon:    { name: 'Darkest Dungeon', sources: [{ type: 'curseforge', slug: 'darkest_dungeon', game_id: 608 }] },

    // ---- mod.io-primary games ----
    squad:              { name: 'Squad', sources: [
        { type: 'workshop', appid: 393380 },
        { type: 'modio', game_id: 362 },
    ]},
    mordhau:            { name: 'Mordhau', sources: [
        { type: 'workshop', appid: 629760 },
        { type: 'modio', game_id: 264 },
    ]},
    insurgency_sandstorm: { name: 'Insurgency: Sandstorm', sources: [
        { type: 'workshop', appid: 581320 },
        { type: 'modio', game_id: 188 },
    ]},
    killing_floor_2:    { name: 'Killing Floor 2', sources: [
        { type: 'workshop', appid: 232090 },
        { type: 'modio', game_id: 50 },
    ]},
    kf2:                { name: 'Killing Floor 2', sources: [
        { type: 'workshop', appid: 232090 },
        { type: 'modio', game_id: 50 },
    ]},
};

export default function SteamModsPanel({ serverId, serverName, gameSlug }) {
    const [loading, setLoading] = useState(false);
    const [installedMods, setInstalledMods] = useState([]);
    const [error, setError] = useState('');
    
    // Search state
    const [showSearch, setShowSearch] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searching, setSearching] = useState(false);
    const [searchError, setSearchError] = useState('');
    const [installing, setInstalling] = useState(null);
    const [page, setPage] = useState(1);
    const [totalResults, setTotalResults] = useState(0);

    // Multi-source: selected source index
    const [activeSourceIdx, setActiveSourceIdx] = useState(0);

    const gameConfig = SUPPORTED_GAMES[gameSlug] || null;
    const isSupported = gameConfig !== null;
    const availableSources = gameConfig?.sources || [];
    const activeSource = availableSources[activeSourceIdx] || availableSources[0];
    const sourceType = activeSource?.type;
    const sourceInfo = SOURCE_INFO[sourceType] || SOURCE_INFO.workshop;

    function authHeaders() {
        const token = getStoredToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    }

    // Fetch installed mods
    async function fetchInstalledMods() {
        if (!serverId || !gameSlug) return;
        setLoading(true);
        setError('');
        try {
            const res = await fetch(
                `${API}/steam-mods/installed/${encodeURIComponent(serverId)}?game_slug=${encodeURIComponent(gameSlug)}`,
                { headers: authHeaders() }
            );
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            setInstalledMods(data.mods || []);
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    }

    // Search mods
    async function searchMods(newPage = 1) {
        if (!searchQuery.trim() && newPage === 1) return;
        setSearching(true);
        setSearchError('');
        if (newPage === 1) setSearchResults([]);

        try {
            let url;
            if (sourceType === 'thunderstore') {
                url = `${API}/steam-mods/thunderstore/search?community=${encodeURIComponent(activeSource.community)}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            } else if (sourceType === 'curseforge') {
                url = `${API}/steam-mods/curseforge/search?game_slug=${encodeURIComponent(activeSource.slug || gameSlug)}&query=${encodeURIComponent(searchQuery)}&page=${newPage}&page_size=20`;
            } else if (sourceType === 'nexus') {
                url = `${API}/steam-mods/nexus/search?game_slug=${encodeURIComponent(gameSlug)}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            } else if (sourceType === 'modio') {
                url = `${API}/steam-mods/modio/search?game_slug=${encodeURIComponent(gameSlug)}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            } else {
                url = `${API}/steam-mods/workshop/search?appid=${activeSource.appid}&q=${encodeURIComponent(searchQuery)}&page=${newPage}`;
            }

            const res = await fetch(url, { headers: authHeaders() });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            
            // Normalize results based on source
            let results = [];
            if (sourceType === 'curseforge') {
                results = (data.mods || []).map(mod => ({
                    id: mod.id,
                    mod_id: mod.id,
                    title: mod.name,
                    name: mod.name,
                    description: mod.summary || mod.description,
                    icon_url: mod.logo?.thumbnailUrl || mod.logo?.url || mod.icon_url,
                    downloads: mod.downloadCount || mod.downloads,
                    namespace: mod.authors?.[0]?.name || mod.author || 'Unknown',
                    curseforge_url: mod.links?.websiteUrl,
                    latest_file: mod.latestFiles?.[0] || mod.latest_file,
                    categories: mod.categories || [],
                    source: 'curseforge',
                }));
            } else if (sourceType === 'nexus') {
                results = (data.mods || []).map(mod => ({
                    id: mod.mod_id || mod.id,
                    mod_id: mod.mod_id || mod.id,
                    title: mod.name || mod.title,
                    name: mod.name || mod.title,
                    description: mod.description || mod.summary || '',
                    icon_url: mod.icon_url || mod.picture_url,
                    downloads: mod.downloads || 0,
                    namespace: mod.author || 'Unknown',
                    page_url: mod.page_url,
                    endorsements: mod.endorsements,
                    version: mod.version,
                    source: 'nexus',
                }));
            } else if (sourceType === 'modio') {
                results = (data.mods || []).map(mod => ({
                    id: mod.mod_id || mod.id,
                    mod_id: mod.mod_id || mod.id,
                    title: mod.name || mod.title,
                    name: mod.name || mod.title,
                    description: mod.description || '',
                    icon_url: mod.icon_url,
                    downloads: mod.downloads || 0,
                    namespace: mod.author || 'Unknown',
                    page_url: mod.page_url,
                    download_url: mod.download_url,
                    version: mod.version,
                    source: 'modio',
                }));
            } else {
                results = data.results || [];
            }
            
            // Check for API error messages
            if (data.error) {
                setSearchError(data.error);
            }
            
            setSearchResults(prev => newPage === 1 ? results : [...prev, ...results]);
            setTotalResults(data.total || data.pagination?.totalCount || 0);
            setPage(newPage);
        } catch (e) {
            setSearchError(e.message);
        } finally {
            setSearching(false);
        }
    }

    // Install mod from Thunderstore
    async function installThunderstoreMod(mod) {
        setInstalling(mod.id);
        try {
            const res = await fetch(`${API}/steam-mods/thunderstore/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    namespace: mod.namespace,
                    name: mod.name,
                    version: mod.version,
                    game_slug: gameSlug,
                    install_dependencies: true
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            const data = await res.json();
            alert(`✅ Installed ${data.installed?.length || 1} mod(s) successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ Failed to install: ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Install mod from CurseForge
    async function installCurseForgeMod(mod) {
        setInstalling(mod.id);
        try {
            // Get latest file if we don't have one
            let fileId = mod.latest_file?.id;
            
            if (!fileId) {
                // Fetch files for this mod
                const filesRes = await fetch(
                    `${API}/steam-mods/curseforge/mod/${mod.mod_id}/files`,
                    { headers: authHeaders() }
                );
                if (filesRes.ok) {
                    const filesData = await filesRes.json();
                    if (filesData.files?.length > 0) {
                        fileId = filesData.files[0].id;
                    }
                }
            }
            
            if (!fileId) {
                throw new Error('No downloadable file found for this mod');
            }
            
            const res = await fetch(`${API}/steam-mods/curseforge/install`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    game_slug: activeSource.slug || gameSlug,
                    mod_id: mod.mod_id,
                    file_id: fileId
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            const data = await res.json();
            alert(`✅ Installed ${mod.name} successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ Failed to install: ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Install mod from Nexus Mods
    async function installNexusMod(mod) {
        setInstalling(mod.id);
        try {
            // First get files list
            const filesRes = await fetch(
                `${API}/steam-mods/nexus/mod/${encodeURIComponent(gameSlug)}/${mod.mod_id}/files`,
                { headers: authHeaders() }
            );
            if (!filesRes.ok) throw new Error('Failed to get mod files');
            const filesData = await filesRes.json();
            const files = filesData.files || [];
            
            // Find the primary/main file
            const primaryFile = files.find(f => f.is_primary) || files[0];
            if (!primaryFile) {
                // Fallback: open the Nexus page for manual download
                if (mod.page_url) {
                    window.open(mod.page_url, '_blank');
                    alert('ℹ️ No direct download available. Opening Nexus Mods page for manual download.');
                } else {
                    throw new Error('No files available for this mod');
                }
                return;
            }

            const res = await fetch(
                `${API}/steam-mods/nexus/install?server_id=${encodeURIComponent(serverId)}&game_slug=${encodeURIComponent(gameSlug)}&mod_id=${mod.mod_id}&file_id=${primaryFile.id}`,
                { method: 'POST', headers: authHeaders() }
            );
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                // If 403, suggest manual download
                if (res.status === 403) {
                    if (mod.page_url) window.open(mod.page_url, '_blank');
                    throw new Error('Nexus Premium required for direct downloads. Opening Nexus page for manual download.');
                }
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            alert(`✅ Installed ${mod.name} successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Install mod from mod.io
    async function installModioMod(mod) {
        setInstalling(mod.id);
        try {
            const res = await fetch(
                `${API}/steam-mods/modio/install?server_id=${encodeURIComponent(serverId)}&game_slug=${encodeURIComponent(gameSlug)}&mod_id=${mod.mod_id}`,
                { method: 'POST', headers: authHeaders() }
            );
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            alert(`✅ Installed ${mod.name} successfully!`);
            await fetchInstalledMods();
        } catch (e) {
            alert(`❌ Failed to install: ${e.message}`);
        } finally {
            setInstalling(null);
        }
    }

    // Uninstall mod
    async function uninstallMod(modName) {
        if (!confirm(`Remove ${modName}?`)) return;
        try {
            const res = await fetch(`${API}/steam-mods/uninstall`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify({
                    server_id: serverId,
                    mod_name: modName,
                    game_slug: gameSlug
                })
            });
            
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || `HTTP ${res.status}`);
            }
            
            await fetchInstalledMods();
        } catch (e) {
            alert(`Failed to uninstall: ${e.message}`);
        }
    }

    useEffect(() => {
        if (isSupported) {
            fetchInstalledMods();
        }
    }, [serverId, gameSlug]);

    // Reset search when switching source
    useEffect(() => {
        setSearchResults([]);
        setSearchQuery('');
        setSearchError('');
        setPage(1);
        setTotalResults(0);
    }, [activeSourceIdx]);

    // Game not supported
    if (!isSupported) {
        return (
            <div className="p-6">
                <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-6 text-center">
                    <FaCube className="text-4xl text-yellow-400 mx-auto mb-4" />
                    <h3 className="text-xl font-bold text-white mb-2">Mod Support Not Available</h3>
                    <p className="text-white/60">
                        This game ({gameSlug}) doesn't have integrated mod support yet.
                    </p>
                    <p className="text-white/40 text-sm mt-2">
                        You can still manually add mods via the Files tab.
                    </p>
                </div>
            </div>
        );
    }

    return (
        <div className="p-6 space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-xl font-bold text-white flex items-center gap-2">
                        <FaCube className="text-brand-400" />
                        Mods for {gameConfig.name}
                    </h2>
                    <p className="text-white/50 text-sm mt-1">
                        {availableSources.length} mod source{availableSources.length !== 1 ? 's' : ''} available
                    </p>
                </div>
                <button
                    onClick={() => setShowSearch(!showSearch)}
                    className="flex items-center gap-2 px-4 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors"
                >
                    <FaSearch /> Browse Mods
                </button>
            </div>

            {/* Source Selector Tabs (only show when multiple sources) */}
            {availableSources.length > 1 && (
                <div className="flex flex-wrap gap-2">
                    {availableSources.map((src, idx) => {
                        const info = SOURCE_INFO[src.type] || SOURCE_INFO.workshop;
                        const Icon = info.icon;
                        const isActive = idx === activeSourceIdx;
                        return (
                            <button
                                key={`${src.type}-${idx}`}
                                onClick={() => setActiveSourceIdx(idx)}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border ${
                                    isActive
                                        ? `${info.bg} border-current ${info.color}`
                                        : 'border-white/10 text-white/50 hover:text-white hover:border-white/30'
                                }`}
                            >
                                <Icon className="text-sm" />
                                {info.label}
                            </button>
                        );
                    })}
                </div>
            )}

            {/* Mod Browser Modal */}
            {showSearch && (
                <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
                    <div className="bg-gray-900 border border-white/10 rounded-xl w-full max-w-4xl shadow-2xl max-h-[85vh] flex flex-col">
                        {/* Header */}
                        <div className="p-4 border-b border-white/10 flex items-center justify-between shrink-0">
                            <h3 className="text-xl font-bold text-white flex items-center gap-2">
                                {React.createElement(sourceInfo.icon, { className: sourceInfo.color })}
                                Browse {sourceInfo.label} Mods
                            </h3>
                            <button onClick={() => setShowSearch(false)} className="text-white/60 hover:text-white">
                                <FaTimes size={20} />
                            </button>
                        </div>

                        {/* Search Bar */}
                        <div className="p-4 border-b border-white/10 shrink-0">
                            <div className="flex gap-2">
                                <div className="relative flex-1">
                                    <FaSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
                                    <input
                                        type="text"
                                        placeholder="Search mods..."
                                        value={searchQuery}
                                        onChange={(e) => setSearchQuery(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && searchMods(1)}
                                        className="w-full pl-10 pr-4 py-2 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/40 focus:outline-none focus:border-brand-500"
                                    />
                                </div>
                                <button
                                    onClick={() => searchMods(1)}
                                    disabled={searching}
                                    className="px-6 py-2 bg-brand-600 hover:bg-brand-500 text-white rounded-lg transition-colors disabled:opacity-50"
                                >
                                    {searching ? 'Searching...' : 'Search'}
                                </button>
                            </div>
                            {searchError && (
                                <p className="text-red-400 text-sm mt-2">{searchError}</p>
                            )}
                        </div>

                        {/* Results */}
                        <div className="flex-1 overflow-y-auto p-4">
                            {searchResults.length === 0 && !searching ? (
                                <div className="text-center text-white/40 py-12">
                                    {searchQuery ? 'No mods found. Try a different search.' : 'Enter a search term to find mods'}
                                </div>
                            ) : (
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                    {searchResults.map(mod => (
                                        <ModCard
                                            key={mod.id}
                                            mod={mod}
                                            installing={installing === mod.id}
                                            onInstall={() => {
                                                if (sourceType === 'thunderstore') {
                                                    installThunderstoreMod(mod);
                                                } else if (sourceType === 'curseforge') {
                                                    installCurseForgeMod(mod);
                                                } else if (sourceType === 'nexus') {
                                                    installNexusMod(mod);
                                                } else if (sourceType === 'modio') {
                                                    installModioMod(mod);
                                                } else {
                                                    alert('Workshop mod installation coming soon');
                                                }
                                            }}
                                            source={sourceType}
                                        />
                                    ))}
                                </div>
                            )}

                            {/* Load More */}
                            {searchResults.length > 0 && searchResults.length < totalResults && (
                                <div className="text-center mt-6">
                                    <button
                                        onClick={() => searchMods(page + 1)}
                                        disabled={searching}
                                        className="px-6 py-2 bg-white/10 hover:bg-white/20 text-white rounded-lg transition-colors disabled:opacity-50"
                                    >
                                        {searching ? 'Loading...' : `Load More (${searchResults.length} of ${totalResults})`}
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Installed Mods */}
            <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                <div className="p-4 border-b border-white/10 flex items-center justify-between">
                    <h3 className="font-semibold text-white flex items-center gap-2">
                        <FaFolder className="text-white/60" />
                        Installed Mods ({installedMods.length})
                    </h3>
                    <button
                        onClick={fetchInstalledMods}
                        className="text-white/60 hover:text-white text-sm"
                    >
                        Refresh
                    </button>
                </div>

                {loading ? (
                    <div className="p-8 text-center">
                        <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full mx-auto" />
                    </div>
                ) : error ? (
                    <div className="p-6 text-center text-red-400">
                        {error}
                    </div>
                ) : installedMods.length === 0 ? (
                    <div className="p-8 text-center text-white/40">
                        No mods installed yet. Click "Browse Mods" to get started!
                    </div>
                ) : (
                    <div className="divide-y divide-white/5">
                        {installedMods.map((mod, idx) => (
                            <div key={mod.name || idx} className="p-4 flex items-center justify-between hover:bg-white/5">
                                <div>
                                    <p className="text-white font-medium">{mod.name}</p>
                                    <p className="text-white/50 text-sm">
                                        {mod.version !== 'unknown' && `v${mod.version} • `}
                                        {mod.type === 'file' ? mod.file : mod.folder}
                                    </p>
                                </div>
                                <button
                                    onClick={() => uninstallMod(mod.folder || mod.file || mod.name)}
                                    className="p-2 text-red-400 hover:bg-red-500/20 rounded-lg transition-colors"
                                    title="Uninstall"
                                >
                                    <FaTrash />
                                </button>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Info Box */}
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
                <h4 className="font-semibold text-blue-400 mb-2">💡 Tips</h4>
                <ul className="text-white/60 text-sm space-y-1">
                    <li>• Most mods require a server restart to take effect</li>
                    {sourceType === 'thunderstore' && (
                        <>
                            <li>• Dependencies are automatically installed</li>
                            <li>• Some mods require BepInEx mod loader</li>
                        </>
                    )}
                    {sourceType === 'curseforge' && (
                        <>
                            <li>• CurseForge hosts mods for many popular games</li>
                            <li>• Check mod compatibility with your game version</li>
                        </>
                    )}
                    {sourceType === 'workshop' && (
                        <li>• Workshop items are downloaded from Steam</li>
                    )}
                    {sourceType === 'nexus' && (
                        <>
                            <li>• Requires NEXUS_API_KEY environment variable for searching</li>
                            <li>• Direct downloads require a Nexus Mods Premium account</li>
                            <li>• Free users can browse and download manually via the Nexus website</li>
                        </>
                    )}
                    {sourceType === 'modio' && (
                        <>
                            <li>• Requires MODIO_API_KEY environment variable</li>
                            <li>• mod.io provides game-specific modding support</li>
                        </>
                    )}
                    {availableSources.length > 1 && (
                        <li>• This game supports {availableSources.length} mod sources — switch between them using the tabs above</li>
                    )}
                </ul>
            </div>
        </div>
    );
}

// Mod Card Component
function ModCard({ mod, installing, onInstall, source }) {
    const pageUrl = mod.page_url || mod.curseforge_url;
    return (
        <div className="bg-white/5 border border-white/10 rounded-lg p-4 flex gap-4">
            {/* Icon */}
            {mod.icon_url ? (
                <img
                    src={mod.icon_url}
                    alt=""
                    className="w-16 h-16 rounded-lg object-cover shrink-0 bg-white/10"
                    onError={(e) => e.target.style.display = 'none'}
                />
            ) : (
                <div className="w-16 h-16 rounded-lg bg-gradient-to-br from-brand-500/30 to-purple-500/30 flex items-center justify-center shrink-0">
                    <FaCube className="text-2xl text-white/60" />
                </div>
            )}

            {/* Info */}
            <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                    <h4 className="text-white font-semibold truncate">{mod.title || mod.name}</h4>
                    {pageUrl && (
                        <a href={pageUrl} target="_blank" rel="noopener noreferrer"
                           className="text-white/30 hover:text-white/60 shrink-0" title="Open in browser">
                            <FaExternalLinkAlt size={11} />
                        </a>
                    )}
                </div>
                <p className="text-white/50 text-sm line-clamp-2 mt-1">
                    {mod.description || 'No description available'}
                </p>
                <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                    {mod.downloads != null && (
                        <span className="flex items-center gap-1">
                            <FaDownload /> {formatNumber(mod.downloads)}
                        </span>
                    )}
                    {mod.endorsements != null && (
                        <span>👍 {formatNumber(mod.endorsements)}</span>
                    )}
                    {mod.version && (
                        <span>v{mod.version}</span>
                    )}
                    {mod.namespace && (
                        <span>by {mod.namespace}</span>
                    )}
                    {source && (
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${SOURCE_INFO[source]?.bg || 'bg-white/10'} ${SOURCE_INFO[source]?.color || 'text-white/60'}`}>
                            {SOURCE_INFO[source]?.label || source}
                        </span>
                    )}
                </div>
            </div>

            {/* Install Button */}
            <div className="shrink-0">
                <button
                    onClick={onInstall}
                    disabled={installing}
                    className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors disabled:opacity-50 flex items-center gap-2"
                >
                    {installing ? (
                        <>
                            <span className="animate-spin">⏳</span> Installing
                        </>
                    ) : (
                        <>
                            <FaDownload /> Install
                        </>
                    )}
                </button>
            </div>
        </div>
    );
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num?.toString() || '0';
}
