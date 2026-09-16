# Extending Steam Game Catalog

Place additional JSON files in this directory to add or override Steam game definitions without modifying Python code. Each file must contain an object where the keys are game slugs and the values match the structure used in `steam_games.py`.

Example:

```
{
  "example_game": {
    "display_name": "Example Game",
    "image": "vendor/game-image:latest",
    "ports": [{"container": 12345, "protocol": "udp"}],
    "env": {"SERVER_PASSWORD": "change-me"}
  }
}
```

When slugs collide, the last file loaded wins, allowing you to override built-in definitions.

## Bundled packs

- `source_engine.json` — Source-engine servers via `ghcr.io/ich777/steamcmd` (CSS on the generic `latest` tag per ich777's docs, plus DoD:S, HL2DM, L4D1, Insurgency 2014, Sven Co-op).
- `survival_sandbox.json` — DST, SCP:SL, Starbound, Wurm Unlimited, Barotrauma, Stationeers, Avorion, Chivalry, Core Keeper via `ghcr.io/ich777/steamcmd:<game>` tags.

All images/tags in these packs were verified against the registries. When adding
a game, prefer an image tag you have confirmed exists (Docker Hub API needs no
auth; for GHCR fetch a pull token first) and mirror the `GAME_ID`/`GAME_NAME`/
`GAME_PORT` conventions of the existing entries.
