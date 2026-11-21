import React from 'react';

/**
 * Bespoke precision SVG icon components crafted for Lynx's glassmorphic UI.
 * Avoids platform emojis in favor of crisp vector geometry with layered depth.
 */

export function MultiCoreCpuIcon({ className = 'w-4 h-4', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      {/* Perimeter bus pins */}
      <path
        d="M9 2v2.5M15 2v2.5M9 19.5V22M15 19.5V22M2 9h2.5M2 15h2.5M19.5 9H22M19.5 15H22"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity="0.7"
      />
      {/* Outer silicon substrate */}
      <rect
        x="4.5"
        y="4.5"
        width="15"
        height="15"
        rx="3"
        fill="currentColor"
        fillOpacity="0.12"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      {/* Four parallel execution core quadrants */}
      <rect x="7.5" y="7.5" width="3.8" height="3.8" rx="0.9" fill="currentColor" />
      <rect x="12.7" y="7.5" width="3.8" height="3.8" rx="0.9" fill="currentColor" opacity="0.82" />
      <rect x="7.5" y="12.7" width="3.8" height="3.8" rx="0.9" fill="currentColor" opacity="0.82" />
      <rect x="12.7" y="12.7" width="3.8" height="3.8" rx="0.9" fill="currentColor" />
    </svg>
  );
}

export function SingleCoreCpuIcon({ className = 'w-4 h-4', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <path
        d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        opacity="0.65"
      />
      <rect
        x="4.5"
        y="4.5"
        width="15"
        height="15"
        rx="3"
        fill="currentColor"
        fillOpacity="0.1"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      {/* Single core node */}
      <rect
        x="9"
        y="9"
        width="6"
        height="6"
        rx="1.2"
        fill="currentColor"
        fillOpacity="0.85"
      />
    </svg>
  );
}

export function ShieldLockIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <path
        d="M12 2.75L4.5 5.95v5.65c0 4.95 3.18 9.28 7.5 10.65 4.32-1.37 7.5-5.7 7.5-10.65V5.95L12 2.75z"
        fill="currentColor"
        fillOpacity="0.14"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <rect
        x="9"
        y="11"
        width="6"
        height="4.75"
        rx="1.2"
        fill="currentColor"
      />
      <path
        d="M10.1 11V9.3a1.9 1.9 0 013.8 0V11"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function UsersBadgeIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      {/* Primary avatar */}
      <circle
        cx="9.5"
        cy="8.5"
        r="3.2"
        fill="currentColor"
        fillOpacity="0.22"
        stroke="currentColor"
        strokeWidth="1.65"
      />
      <path
        d="M3.75 18.75a5.75 5.75 0 0111.5 0"
        fill="currentColor"
        fillOpacity="0.15"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinecap="round"
      />
      {/* Secondary member & access ring */}
      <circle
        cx="16.5"
        cy="9.5"
        r="2.4"
        stroke="currentColor"
        strokeWidth="1.5"
        opacity="0.75"
      />
      <path
        d="M16.5 14.3a4.2 4.2 0 013.75 4.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.75"
      />
    </svg>
  );
}

export function ArchiveImportIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      {/* Archive container body */}
      <path
        d="M4 7.5A2.5 2.5 0 016.5 5h4.2l1.6 1.8h5.2A2.5 2.5 0 0120 9.3v8.2a2.5 2.5 0 01-2.5 2.5h-11A2.5 2.5 0 014 17.5v-10z"
        fill="currentColor"
        fillOpacity="0.14"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinejoin="round"
      />
      {/* Precision zipper / package core + import vector */}
      <path
        d="M12 10.5v5.2m0 0l-2.3-2.2m2.3 2.2l2.3-2.2"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M8.5 18h7"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.65"
      />
    </svg>
  );
}

export function NetworkFirewallIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="8.5"
        fill="currentColor"
        fillOpacity="0.1"
        stroke="currentColor"
        strokeWidth="1.5"
      />
      <ellipse
        cx="12"
        cy="12"
        rx="4"
        ry="8.5"
        stroke="currentColor"
        strokeWidth="1.4"
        opacity="0.7"
      />
      <path
        d="M3.8 12h16.4M5.4 7.8h13.2M5.4 16.2h13.2"
        stroke="currentColor"
        strokeWidth="1.35"
        strokeLinecap="round"
        opacity="0.65"
      />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
    </svg>
  );
}

export function ApiKeyTokenIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <circle
        cx="8.2"
        cy="12"
        r="4.2"
        fill="currentColor"
        fillOpacity="0.16"
        stroke="currentColor"
        strokeWidth="1.65"
      />
      <circle cx="8.2" cy="12" r="1.4" fill="currentColor" />
      <path
        d="M12.4 12H21v2.6M17.5 12v2.1"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function AuditTrailIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <rect
        x="4"
        y="3.5"
        width="16"
        height="17"
        rx="2.6"
        fill="currentColor"
        fillOpacity="0.12"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M7.5 12.2h2.2l1.6-3.4 2 6.2 1.4-2.8h1.8"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M8 7.2h8M8 17.2h5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        opacity="0.55"
      />
    </svg>
  );
}

export function RoleMatrixIcon({ className = 'w-5 h-5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className={className}
      style={style}
      aria-hidden="true"
    >
      <rect x="4" y="4" width="7" height="7" rx="1.8" fill="currentColor" fillOpacity="0.2" stroke="currentColor" strokeWidth="1.6" />
      <rect x="13" y="4" width="7" height="7" rx="1.8" stroke="currentColor" strokeWidth="1.6" opacity="0.7" />
      <rect x="4" y="13" width="7" height="7" rx="1.8" stroke="currentColor" strokeWidth="1.6" opacity="0.7" />
      <path d="M14.2 16.5l1.6 1.6 3.2-3.4" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TipSparkIcon({ className = 'w-4 h-4', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
      <path
        d="M12 3l2.2 5.4L19.8 10l-5.6 1.6L12 17l-2.2-5.4L4.2 10l5.6-1.6L12 3z"
        fill="currentColor"
        fillOpacity="0.22"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M18.5 16.5l.8 2 .8-2 2-.8-2-.8-.8-2-.8 2-2 .8 2 .8z" fill="currentColor" opacity="0.8" />
    </svg>
  );
}

export function FileDocIcon({ className = 'w-4 h-4', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
      <path
        d="M6.5 3.5h7l4.5 4.5v12.5a1.5 1.5 0 01-1.5 1.5h-10A1.5 1.5 0 015 20.5V5a1.5 1.5 0 011.5-1.5z"
        fill="currentColor"
        fillOpacity="0.14"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M13.5 3.5V8H18" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M8.5 12h7M8.5 15.5h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.7" />
    </svg>
  );
}

export function WarningVectorIcon({ className = 'w-4 h-4', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
      <path
        d="M10.4 4.2a1.85 1.85 0 013.2 0l7.1 12.3a1.85 1.85 0 01-1.6 2.75H4.9a1.85 1.85 0 01-1.6-2.75l7.1-12.3z"
        fill="currentColor"
        fillOpacity="0.16"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinejoin="round"
      />
      <path d="M12 9.2v4.3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="12" cy="16.1" r="1" fill="currentColor" />
    </svg>
  );
}

export function CloseVectorIcon({ className = 'w-3.5 h-3.5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
      <path
        d="M6.5 6.5l11 11M17.5 6.5l-11 11"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function EndorseVectorIcon({ className = 'w-3.5 h-3.5', size }) {
  const style = size ? { width: size, height: size } : undefined;
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} style={style} aria-hidden="true">
      <path
        d="M12 3.5l2.6 5.2 5.8.8-4.2 4.1 1 5.7-5.2-2.7-5.2 2.7 1-5.7-4.2-4.1 5.8-.8L12 3.5z"
        fill="currentColor"
        fillOpacity="0.22"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}
