import React from 'react';

/**
 * Player Avatar with Crafatar (like Crafty Controller)
 * Shows the Minecraft head of the player.
 */
const PlayerAvatar = ({ uuid, name, size = 32, className = '' }) => {
  // Fallback: show initials if no UUID available
  if (!uuid) {
    return (
      <div
        className={`rounded-full bg-gray-600 flex items-center justify-center text-white font-bold ${className}`}
        style={{ width: size, height: size, fontSize: size * 0.4 }}
      >
        {name?.charAt(0).toUpperCase() || '?'}
      </div>
    );
  }

  // Crafatar URL for the avatar (like Crafty Controller uses)
  const avatarUrl = `https://crafatar.com/avatars/${uuid}?size=${size}`;
  const headUrl = `https://crafatar.com/renders/head/${uuid}?size=${size}`;

  return (
    <img
      src={avatarUrl}
      alt={name || 'Player'}
      className={`rounded-full border border-gray-600 ${className}`}
      style={{ width: size, height: size }}
      onError={(e) => {
        // If avatar fails to load: try head render
        e.target.src = headUrl;
        e.target.onerror = () => {
          // If head also fails: show initials
          e.target.style.display = 'none';
          const parent = e.target.parentElement;
          const initials = name?.charAt(0).toUpperCase() || '?';
          const fallback = document.createElement('div');
          fallback.className = `rounded-full bg-blue-600 flex items-center justify-center text-white font-bold ${className}`;
          fallback.style.width = `${size}px`;
          fallback.style.height = `${size}px`;
          fallback.style.fontSize = `${size * 0.4}px`;
          fallback.textContent = initials;
          parent.appendChild(fallback);
        };
      }}
    />
  );
};

export default PlayerAvatar;