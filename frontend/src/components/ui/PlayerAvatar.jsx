import React from 'react';

/**
 * Player Avatar with Crafatar (like Crafty Controller)
 * Shows the Minecraft head of the player.
 */
const PlayerAvatar = ({ uuid, name, size = 32, className = '' }) => {
  // Primary URL: crafatar when UUID is known, otherwise mc-heads by name (no Mojang lookup needed)
  // This fixes the "online = initial, offline = head" bug: logs/RCON only give a name, not a UUID.
  const hasUuid = typeof uuid === 'string' && uuid.trim() !== '';
  const hasName = typeof name === 'string' && name.trim() !== '';
  const safeName = hasName ? name.trim() : '';

  // Fallback initials
  const initialsFallback = (
    <div
      className={`rounded-full bg-gray-600 flex items-center justify-center text-white font-bold ${className}`}
      style={{ width: size, height: size, fontSize: size * 0.4 }}
    >
      {safeName.charAt(0).toUpperCase() || '?'}
    </div>
  );

  if (!hasUuid && !hasName) return initialsFallback;

  const crafatarAvatar = hasUuid ? `https://crafatar.com/avatars/${uuid}?size=${size}` : null;
  const crafatarHead = hasUuid ? `https://crafatar.com/renders/head/${uuid}?size=${size}` : null;
  const mcHeadsUrl = hasName ? `https://mc-heads.net/avatar/${encodeURIComponent(safeName)}/${size}` : null;

  // Prefer crafatar when we have a UUID, otherwise mc-heads directly
  const primaryUrl = crafatarAvatar || mcHeadsUrl;
  const secondaryUrl = hasUuid ? (mcHeadsUrl || crafatarHead) : null;
  const tertiaryUrl = hasUuid ? crafatarHead : null;

  if (!primaryUrl) return initialsFallback;

  return (
    <img
      src={primaryUrl}
      alt={name || 'Player'}
      className={`rounded-full border border-gray-600 ${className}`}
      style={{ width: size, height: size }}
      onError={(e) => {
        const img = e.target;
        // Chain: primary -> secondary (mc-heads) -> tertiary (crafatar head) -> initials
        if (secondaryUrl && img.src !== secondaryUrl) {
          img.src = secondaryUrl;
          return;
        }
        if (tertiaryUrl && img.src !== tertiaryUrl) {
          img.src = tertiaryUrl;
          img.onerror = () => {
            img.style.display = 'none';
            const parent = img.parentElement;
            if (!parent) return;
            const initials = safeName.charAt(0).toUpperCase() || '?';
            const fallback = document.createElement('div');
            fallback.className = `rounded-full bg-blue-600 flex items-center justify-center text-white font-bold ${className}`;
            fallback.style.width = `${size}px`;
            fallback.style.height = `${size}px`;
            fallback.style.fontSize = `${size * 0.4}px`;
            fallback.textContent = initials;
            parent.appendChild(fallback);
          };
          return;
        }
        // Final fallback to initials
        img.style.display = 'none';
        const parent = img.parentElement;
        if (!parent) return;
        const initials = safeName.charAt(0).toUpperCase() || '?';
        const fallback = document.createElement('div');
        fallback.className = `rounded-full bg-gray-600 flex items-center justify-center text-white font-bold ${className}`;
        fallback.style.width = `${size}px`;
        fallback.style.height = `${size}px`;
        fallback.style.fontSize = `${size * 0.4}px`;
        fallback.textContent = initials;
        parent.appendChild(fallback);
      }}
    />
  );
};

export default PlayerAvatar;