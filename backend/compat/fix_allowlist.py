import json
from pathlib import Path

path = Path('C:/Users/phili/Documents/GitHub/Minecraft-Controller/backend/compat/allowlist.json')
with open(path, 'r') as f:
    data = json.load(f)

# Remove client-only mods from force_server
client_only_to_remove = {'sodium', 'sodium-extra', 'sodiumextra', 'iris', 'rubidium', 'oculus', 'embeddium', 'canvas', 'optifine', 'optifabric'}
data['force_server'] = [x for x in data['force_server'] if x not in client_only_to_remove]

# Also remove duplicates in force_client
seen = set()
new_client = []
for x in data['force_client']:
    if x not in seen:
        seen.add(x)
        new_client.append(x)
data['force_client'] = new_client

# Deduplicate force_server too
seen = set()
new_server = []
for x in data['force_server']:
    if x not in seen:
        seen.add(x)
        new_server.append(x)
data['force_server'] = new_server

with open(path, 'w') as f:
    json.dump(data, f, indent=2)

print('Fixed allowlist.json')
print('force_server count:', len(data['force_server']))
print('force_client count:', len(data['force_client']))
print('sodium in force_server:', 'sodium' in data['force_server'])
print('sodium in force_client:', 'sodium' in data['force_client'])