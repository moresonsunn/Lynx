import React from 'react';
import ReactDOM from 'react-dom/client';
// Use the new router-based App for proper URL routing
import AppWithRouter from './AppRouter';
import './index.css';
import * as serviceWorker from './serviceWorker';

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <React.StrictMode>
    <AppWithRouter />
  </React.StrictMode>
);

// Unregister any previously installed service worker. A stale SW that
// precached the old JS bundle makes Ctrl+R appear to "break" the app
// (old chunks 404 after a new deploy). We use no offline caching here.
serviceWorker.unregister();
// Proactively clean up any existing worker registrations left from older builds
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then(regs => {
    regs.forEach(r => {
      // Keep the current no-op SW if it exists, but force it to update
      try { r.update(); } catch {}
    });
  }).catch(() => {});
}
