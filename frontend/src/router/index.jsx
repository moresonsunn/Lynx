import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

// Lazy load pages for code splitting
const DashboardPage = React.lazy(() => import('../pages/DashboardPage'));
const ServersPage = React.lazy(() => import('../pages/ServersPage'));
const ServerDetailsPage = React.lazy(() => import('../pages/ServerDetailsPage'));
const TemplatesPage = React.lazy(() => import('../pages/TemplatesPage'));
const UsersPage = React.lazy(() => import('../pages/UsersPage'));
const SettingsPage = React.lazy(() => import('../pages/SettingsPage'));
const LoginPage = React.lazy(() => import('../pages/LoginPage'));
const MustChangePasswordPage = React.lazy(() => import('../pages/MustChangePasswordPage'));

// Loading fallback component
const PageLoader = () => (
  <div className="flex items-center justify-center h-screen bg-ink">
    <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full"></div>
  </div>
);

// Protected route wrapper
export function ProtectedRoute({ children, isAuthenticated, mustChangePassword }) {
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  if (mustChangePassword) {
    return <Navigate to="/change-password" replace />;
  }
  
  return children;
}

// Admin-only route wrapper
export function AdminRoute({ children, isAuthenticated, isAdmin }) {
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  
  return children;
}

// Main router component
export function AppRouter({ 
  isAuthenticated, 
  isAdmin, 
  mustChangePassword,
  currentUser,
  onLogout,
  // Pass through any other props needed by child components
  ...appProps 
}) {
  return (
    <BrowserRouter>
      <React.Suspense fallback={<PageLoader />}>
        <Routes>
          {/* Public routes */}
          <Route 
            path="/login" 
            element={
              isAuthenticated ? (
                <Navigate to="/" replace />
              ) : (
                <LoginPage {...appProps} />
              )
            } 
          />
          
          <Route 
            path="/change-password" 
            element={
              !isAuthenticated ? (
                <Navigate to="/login" replace />
              ) : (
                <MustChangePasswordPage {...appProps} />
              )
            } 
          />
          
          {/* Protected routes */}
          <Route 
            path="/" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <DashboardPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/servers" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <ServersPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/servers/:serverId" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <ServerDetailsPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/servers/:serverId/:tab" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <ServerDetailsPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          <Route 
            path="/templates" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <TemplatesPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          {/* Admin-only routes */}
          <Route 
            path="/users" 
            element={
              <AdminRoute isAuthenticated={isAuthenticated} isAdmin={isAdmin}>
                <UsersPage {...appProps} />
              </AdminRoute>
            } 
          />
          
          <Route 
            path="/settings" 
            element={
              <ProtectedRoute isAuthenticated={isAuthenticated} mustChangePassword={mustChangePassword}>
                <SettingsPage {...appProps} />
              </ProtectedRoute>
            } 
          />
          
          {/* Catch-all redirect */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </React.Suspense>
    </BrowserRouter>
  );
}

export default AppRouter;
