import React from 'react';
import { createBrowserRouter, RouterProvider, Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../context/AppContext';

import AppLayout from '../components/AppLayout';
import LoginPage from '../pages/LoginPage';
import MustChangePasswordPage from '../pages/MustChangePasswordPage';
import DashboardPage from '../pages/DashboardPage';
import ServersPage from '../pages/ServersPage';
import ServerDetailsPage from '../pages/ServerDetailsPage';
import TemplatesPage from '../pages/TemplatesPage';
import UsersPage from '../pages/UsersPage';
import SettingsPage from '../pages/SettingsPage';
import SteamGamesPage from '../pages/SteamGamesPage';
import CreateSchedulePage from '../pages/CreateSchedulePage';

function ProtectedRoute() {
  const { isAuthenticated, loading, mustChangePassword } = useAuth();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-ink">
        <div className="animate-spin w-8 h-8 border-4 border-brand-500 border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (mustChangePassword) {
    return <Navigate to="/change-password" replace />;
  }

  return <Outlet />;
}

function AdminRoute() {
  const { isAdmin, loading } = useAuth();

  if (loading) {
    return null;
  }

  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

export const router = createBrowserRouter([
  {
    path: '/login',
    element: <LoginPage />,
  },
  {
    path: '/change-password',
    element: <MustChangePasswordPage />,
  },
  {
    element: <ProtectedRoute />,
    children: [
      {
        element: <AppLayout />,
        children: [
          {
            path: '/',
            element: <DashboardPage />,
          },
          {
            path: '/servers',
            element: <ServersPage />,
          },
          {
            path: '/servers/:serverId',
            element: <ServerDetailsPage />,
          },
          {
            path: '/servers/:serverId/:tab',
            element: <ServerDetailsPage />,
          },
          {
            path: '/servers/:serverId/schedules/new',
            element: <CreateSchedulePage />,
          },
          {
            path: '/templates',
            element: <TemplatesPage />,
          },
          {
            path: '/steam',
            element: <SteamGamesPage />,
          },
          {
            path: '/settings',
            element: <SettingsPage />,
          },
          {
            element: <AdminRoute />,
            children: [
              {
                path: '/users',
                element: <UsersPage />,
              },
            ],
          },
        ],
      },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}

export default AppRouter;
