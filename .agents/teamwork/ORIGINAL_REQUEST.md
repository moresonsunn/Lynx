# Original User Request

## Initial Request — 2026-11-07T16:05:40Z

Implement an interactive modpack update button with version selection for installed Minecraft servers and track/record mods placed on the Client-Only-Allow list.

Working directory: c:\Users\phili\Documents\GitHub\Minecraft-Controller
Integrity mode: development

## Requirements

### R1. Modpack Update Button & Version Selection
In the server management interface (Server Details / Mod Manager), provide an update button when a modpack update is available or when the user wants to update the installed modpack. The update must not occur automatically in the background; the user must be able to select the target version and trigger the update manually. The update flow downloads and applies the new modpack version, updates or adds new mods, cleans up outdated mod files from previous versions, and runs client-side mod detection/filtering on the updated mods.

### R2. Client-Only-Allowlist Recording & Tracking
When mods are added to or managed within the Client-Only-Allow list, record and track their addition with relevant details (such as pattern/mod name, timestamp, and status). Display these recorded allowlist entries clearly in the Server Details / Client Mod Filter interface so that users can see which mods have been placed on the allowlist and track their history.

## Acceptance Criteria

### Modpack Update
- [ ] An update button is present in the server details / mod management UI for servers with an installed modpack.
- [ ] Clicking the update button allows the user to view and choose available target versions for the modpack before confirming the update.
- [ ] Triggering the update executes a backup and updates modpack files/mods to the selected version without requiring manual file copying.
- [ ] Removed or replaced mods from the previous version are cleaned up so no conflicting duplicates remain.
- [ ] The client-side mod detection/filter is applied to newly downloaded/updated mods, preserving whitelisted mods according to the allowlist.
- [ ] Backend API endpoints support querying available update versions and executing the versioned update for the server.

### Client-Only-Allowlist Tracking
- [ ] Adding a mod or pattern to the Client-Only-Allow list records the entry (including mod/pattern identifier and timestamp/status).
- [ ] The Client Mod Filter panel displays the recorded allowlist entries and their status.
- [ ] Allowlist entries can be viewed and removed through the UI and backend endpoints.

### Verification
- [ ] Automated tests (e.g. pytest for backend routes, update logic, and allowlist tracking) pass successfully.
- [ ] Frontend build (`npm run build` or equivalent) succeeds without errors.

---

### Execution Context & Paths
- Working directory: c:\Users\phili\Documents\GitHub\Minecraft-Controller
- State folder: c:\Users\phili\Documents\GitHub\Minecraft-Controller\.agents\teamwork\orchestrator_1
- Original request file: c:\Users\phili\Documents\GitHub\Minecraft-Controller\.agents\teamwork\ORIGINAL_REQUEST.md
- Notice: The user requested plan alignment in German if presenting plans or interacting.
