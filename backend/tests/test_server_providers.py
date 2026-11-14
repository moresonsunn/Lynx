"""Unit tests for Minecraft-Controller server providers.

Verifies Vanilla, Paper, Folia, Forge, and NeoForge providers across
API communication, version listing, download URL resolution, channel filtering,
coordinate parsing, and version helper classifications. All network calls are mocked.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.server_providers import providers
from backend.server_providers.vanilla import VanillaProvider
from backend.server_providers.paper import PaperProvider
from backend.server_providers.folia import FoliaProvider
from backend.server_providers.forge import ForgeProvider
from backend.server_providers.neoforge import NeoForgeProvider


# ==============================================================================
# 1. Provider Registry Tests
# ==============================================================================

class TestProviderRegistry:
    def test_registered_providers_include_core_platforms(self):
        names = providers.get_provider_names()
        assert "vanilla" in names
        assert "paper" in names
        assert "folia" in names
        assert "forge" in names
        assert "neoforge" in names

    def test_get_folia_provider_instance(self):
        p = providers.get_provider("folia")
        assert isinstance(p, FoliaProvider)
        assert p.name == "folia"

    def test_unknown_provider_raises_error(self):
        with pytest.raises(ValueError, match="Unknown server type"):
            providers.get_provider("nonexistent_loader_xyz")


# ==============================================================================
# 2. VanillaProvider Unit Tests
# ==============================================================================

class TestVanillaProvider:
    @pytest.fixture
    def provider(self):
        return VanillaProvider()

    def test_list_versions_success(self, provider):
        mock_manifest = {
            "versions": [
                {"id": "1.21.1", "type": "release"},
                {"id": "1.20.4", "type": "release"},
                {"id": "24w40a", "type": "snapshot"},
                {"id": "1.16.5", "type": "release"},
                {"id": "1.12.2", "type": "release"},
            ]
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_manifest
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            versions = provider.list_versions()
            assert "1.21.1" in versions
            assert "1.20.4" in versions
            assert "1.16.5" in versions
            assert "1.12.2" in versions

    def test_list_versions_network_failure_raises(self, provider):
        with patch("requests.get", side_effect=requests.RequestException("Mojang API down")):
            with pytest.raises(requests.RequestException):
                provider.list_versions()

    def test_get_download_url_success(self, provider):
        mock_manifest = {
            "versions": [
                {"id": "1.21.1", "url": "https://piston-meta.mojang.com/v1/packages/1.21.1.json"},
            ]
        }
        mock_version_meta = {
            "downloads": {
                "server": {
                    "url": "https://piston-data.mojang.com/v1/objects/testsha/server.jar"
                }
            }
        }
        with patch("requests.get") as mock_get:
            manifest_resp = MagicMock()
            manifest_resp.json.return_value = mock_manifest
            manifest_resp.raise_for_status.return_value = None

            meta_resp = MagicMock()
            meta_resp.json.return_value = mock_version_meta
            meta_resp.raise_for_status.return_value = None

            mock_get.side_effect = [manifest_resp, meta_resp]

            url = provider.get_download_url("1.21.1")
            assert url == "https://piston-data.mojang.com/v1/objects/testsha/server.jar"

    def test_get_download_url_version_not_found(self, provider):
        mock_manifest = {"versions": [{"id": "1.20.4", "url": "https://..."}]}
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_manifest
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            with pytest.raises(ValueError, match="Unknown vanilla version"):
                provider.get_download_url("1.99.9")

    def test_get_download_url_missing_server_entry(self, provider):
        mock_manifest = {"versions": [{"id": "1.21.1", "url": "https://piston-meta.mojang.com/v1/1.21.1.json"}]}
        mock_version_meta = {"downloads": {"client": {"url": "https://client.jar"}}}
        with patch("requests.get") as mock_get:
            manifest_resp = MagicMock()
            manifest_resp.json.return_value = mock_manifest
            manifest_resp.raise_for_status.return_value = None

            meta_resp = MagicMock()
            meta_resp.json.return_value = mock_version_meta
            meta_resp.raise_for_status.return_value = None

            mock_get.side_effect = [manifest_resp, meta_resp]

            with pytest.raises(ValueError, match="No server jar for vanilla version"):
                provider.get_download_url("1.21.1")


# ==============================================================================
# 3. PaperProvider Unit Tests
# ==============================================================================

class TestPaperProvider:
    @pytest.fixture
    def provider(self):
        return PaperProvider()

    def test_list_versions_flattening(self, provider):
        mock_data = {
            "versions": {
                "1.21": ["1.21.4", "1.21.1"],
                "1.20": ["1.20.4", "1.20.2", "1.20.1"],
                "1.16": ["1.16.5"],
            }
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_data
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            versions = provider.list_versions()
            assert "1.21.4" in versions
            assert "1.21.1" in versions
            assert "1.20.4" in versions
            assert "1.16.5" in versions
            assert len(versions) == 6

    def test_get_download_url_prefers_stable(self, provider):
        mock_builds = [
            {
                "id": 102,
                "channel": "EXPERIMENTAL",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/exp-102.jar"}}
            },
            {
                "id": 101,
                "channel": "STABLE",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/stable-101.jar"}}
            },
        ]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            url = provider.get_download_url("1.20.4")
            assert url == "https://fill-data.papermc.io/stable-101.jar"

    def test_get_download_url_fallback_when_no_stable(self, provider):
        mock_builds = [
            {
                "id": 50,
                "channel": "ALPHA",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/alpha-50.jar"}}
            }
        ]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            url = provider.get_download_url("1.21.4")
            assert url == "https://fill-data.papermc.io/alpha-50.jar"

    def test_get_download_url_no_builds_raises_error(self, provider):
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = []
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            with pytest.raises(ValueError, match="No builds found for Paper version"):
                provider.get_download_url("1.99.9")


# ==============================================================================
# 4. FoliaProvider Unit Tests
# ==============================================================================

class TestFoliaProvider:
    @pytest.fixture
    def provider(self):
        return FoliaProvider()

    def test_provider_name_and_instantiation(self, provider):
        assert provider.name == "folia"

    def test_list_versions_parses_groups(self, provider):
        mock_fill_resp = {
            "versions": {
                "1.21": ["1.21.4", "1.21.1"],
                "1.20": ["1.20.4", "1.20.2", "1.20.1"],
                "1.19": ["1.19.4"],
            }
        }
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_fill_resp
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            versions = provider.list_versions()
            assert "1.21.4" in versions
            assert "1.20.4" in versions
            assert "1.19.4" in versions
            assert len(versions) == 6

    def test_list_versions_handles_api_exception(self, provider):
        with patch("requests.get", side_effect=requests.RequestException("Fill v3 502")):
            versions = provider.list_versions()
            assert versions == []

    def test_get_download_url_prefers_stable_if_present(self, provider):
        mock_builds = [
            {
                "id": 12,
                "channel": "ALPHA",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/folia-alpha-12.jar"}}
            },
            {
                "id": 10,
                "channel": "STABLE",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/folia-stable-10.jar"}}
            },
        ]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            url = provider.get_download_url("1.20.4")
            assert url == "https://fill-data.papermc.io/folia-stable-10.jar"

    def test_get_download_url_selects_alpha_channel_when_stable_absent(self, provider):
        # Most Folia releases are ALPHA/EXPERIMENTAL
        mock_builds = [
            {
                "id": 35,
                "channel": "ALPHA",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/folia-1.21.1-35.jar"}}
            },
            {
                "id": 34,
                "channel": "ALPHA",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/folia-1.21.1-34.jar"}}
            },
        ]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            url = provider.get_download_url("1.21.1")
            assert url == "https://fill-data.papermc.io/folia-1.21.1-35.jar"

    def test_get_download_url_selects_experimental_channel(self, provider):
        mock_builds = [
            {
                "id": 5,
                "channel": "EXPERIMENTAL",
                "downloads": {"server:default": {"url": "https://fill-data.papermc.io/folia-exp-5.jar"}}
            }
        ]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            url = provider.get_download_url("1.20.2")
            assert url == "https://fill-data.papermc.io/folia-exp-5.jar"

    def test_get_download_url_no_builds_raises_value_error(self, provider):
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = []
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            with pytest.raises(ValueError, match="No builds found for Folia version"):
                provider.get_download_url("1.18.2")

    def test_get_download_url_no_download_entry_raises_error(self, provider):
        mock_builds = [{"id": 1, "channel": "ALPHA", "downloads": {}}]
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_builds
            mock_resp.raise_for_status.return_value = None
            mock_get.return_value = mock_resp

            with pytest.raises(ValueError, match="No downloadable build found for Folia version"):
                provider.get_download_url("1.20.4")


# ==============================================================================
# 5. ForgeProvider Unit Tests
# ==============================================================================

class TestForgeProvider:
    @pytest.fixture
    def provider(self):
        p = ForgeProvider()
        p._cached_versions = None
        p._cached_promotions = None
        return p

    def test_extract_mc_version(self, provider):
        assert provider.extract_mc_version("1.20.1-47.3.0") == "1.20.1"
        assert provider.extract_mc_version("forge-1.12.2-14.23.5.2859") == "1.12.2"
        assert provider.extract_mc_version("1.16.5") == "1.16.5"
        assert provider.extract_mc_version("1.21.1") == "1.21.1"

    def test_is_modern(self, provider):
        # 1.12.2 and 1.16.5 are legacy (direct jar)
        assert provider.is_modern("1.12.2") is False
        assert provider.is_modern("1.16.5") is False
        assert provider.is_modern("1.16.5-36.2.34") is False
        # 1.17+ and 1.20+ are modern (run.sh / user_jvm_args.txt)
        assert provider.is_modern("1.18.2") is True
        assert provider.is_modern("1.20.1") is True
        assert provider.is_modern("1.20.1-47.3.0") is True
        assert provider.is_modern("1.21.1") is True

    def test_get_expected_launch_type(self, provider):
        assert provider.get_expected_launch_type("1.12.2") == "jar"
        assert provider.get_expected_launch_type("1.16.5") == "jar"
        assert provider.get_expected_launch_type("1.20.1") == "run_script"
        assert provider.get_expected_launch_type("1.21.1") == "run_script"

    def test_get_java_version(self, provider):
        # Forge 1.12.2 and 1.16.5 strictly require Java 8 (or 11)
        assert provider.get_java_version("1.12.2") == 8
        assert provider.get_java_version("1.16.5") == 8
        assert provider.get_java_version("1.16.5-36.2.34") == 8
        # Forge 1.20 - 1.20.4 require Java 17
        assert provider.get_java_version("1.20.1") == 17
        assert provider.get_java_version("1.20.4") == 17
        # Forge 1.20.6 / 1.21+ require Java 21
        assert provider.get_java_version("1.20.6") == 21
        assert provider.get_java_version("1.21.1") == 21
        # Snapshot 26+ requires Java 25
        assert provider.get_java_version("26.1") == 25

    def test_best_forge_version_prefers_recommended(self, provider):
        promotions = {
            "1.20.1-recommended": "47.2.0",
            "1.20.1-latest": "47.3.0",
        }
        with patch.object(provider, "_get_promotions", return_value=promotions):
            assert provider.get_best_forge_version("1.20.1") == "47.2.0"

    def test_best_forge_version_falls_back_to_latest(self, provider):
        promotions = {
            "1.20.4-latest": "49.0.30",
        }
        with patch.object(provider, "_get_promotions", return_value=promotions):
            assert provider.get_best_forge_version("1.20.4") == "49.0.30"

    def test_resolve_installer_url_pattern_1(self, provider):
        with patch("requests.head") as mock_head:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_head.return_value = mock_resp

            url = provider._resolve_installer_url("1.20.1", "47.3.0")
            assert "1.20.1-47.3.0/forge-1.20.1-47.3.0-installer.jar" in url


# ==============================================================================
# 6. NeoForgeProvider Unit Tests
# ==============================================================================

class TestNeoForgeProvider:
    @pytest.fixture
    def provider(self):
        p = NeoForgeProvider()
        p._cached_versions = None
        p._cached_neoforge_versions = None
        p._cached_mc_mappings = {}
        return p

    def test_is_modern(self, provider):
        # All NeoForge releases are modern
        assert provider.is_modern("1.20.4") is True
        assert provider.is_modern("20.4.253") is True
        assert provider.is_modern("1.21.1") is True

    def test_get_expected_launch_type(self, provider):
        assert provider.get_expected_launch_type("1.20.4") == "run_script"
        assert provider.get_expected_launch_type("1.21.1") == "run_script"

    def test_get_java_version_mc_and_neoforge_formats(self, provider):
        # 1.20.2 - 1.20.4 (or 20.2 - 20.4) require Java 17
        assert provider.get_java_version("1.20.2") == 17
        assert provider.get_java_version("1.20.4") == 17
        assert provider.get_java_version("20.4.253") == 17
        # 1.20.6 / 1.21+ (or 20.6 / 21+) require Java 21
        assert provider.get_java_version("1.20.6") == 21
        assert provider.get_java_version("1.21.1") == 21
        assert provider.get_java_version("20.6.144") == 21
        assert provider.get_java_version("21.1.266") == 21
        # Snapshot 26+ requires Java 25
        assert provider.get_java_version("26.1") == 25

    def test_infer_mc_version_from_neoforge(self, provider):
        assert provider._infer_mc_version_from_neoforge("20.4.253") == "1.20.4"
        assert provider._infer_mc_version_from_neoforge("21.1.266") == "1.21.1"
        assert provider._infer_mc_version_from_neoforge("21.0.167") == "1.21"
        # Major < 20 is invalid
        assert provider._infer_mc_version_from_neoforge("14.23.5.2859") is None

    def test_get_download_url(self, provider):
        with patch.object(provider, "get_latest_neoforge_version", return_value="20.4.253"):
            url = provider.get_download_url("1.20.4")
            assert "20.4.253/neoforge-20.4.253-installer.jar" in url
