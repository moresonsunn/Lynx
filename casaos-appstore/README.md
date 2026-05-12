# Lynx — CasaOS App Store

Third-party CasaOS app store for installing Lynx on CasaOS.

## Installation

Add one of these URLs as a Custom Source in CasaOS:

**From GitHub (raw):**

```
https://raw.githubusercontent.com/moresonsunn/Lynx/main/casaos-appstore/index.json
```

**From GitHub Releases (recommended):**

```
https://github.com/moresonsunn/Lynx/releases/latest/download/lynx.zip
```

Then install "Lynx (Unified)" from the app store.

## Structure

```
casaos-appstore/
  index.json                # App catalog consumed by CasaOS
  Apps/
    lynx/
      docker-compose.yml    # CasaOS manifest (compose + x-casaos metadata)
```

## Updating

1. Bump the version and image tags in the manifest
2. Rebuild the zip:
   ```bash
   python scripts/package_casaos_store.py
   ```
3. Commit the updated manifest and archive
4. Tag a release and push
5. Refresh the custom source in CasaOS

## Publishing via GitHub Releases

1. Push the commit with updated manifests
2. Create or update a GitHub release tagged `latest`
3. The `lynx.zip` asset is served at `https://github.com/<org>/<repo>/releases/latest/download/lynx.zip`
4. Use that URL as the CasaOS custom source
