import React, { useMemo, useState } from 'react';
import { FaLock } from 'react-icons/fa';
import { useTranslation } from '../i18n/I18nContext';

function validateNewPassword(password, t) {
  if (!password || password.length < 8) return t('auth.passwordMinLength');
  if (!/[A-Z]/.test(password)) return t('auth.passwordUppercase');
  if (!/[a-z]/.test(password)) return t('auth.passwordLowercase');
  if (!/[0-9]/.test(password)) return t('auth.passwordDigit');
  return '';
}

export default function MustChangePasswordPage({ appName, apiBaseUrl, onComplete, onLogout, authHeaders }) {
  const { t } = useTranslation();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const passwordHint = useMemo(() => validateNewPassword(newPassword, t), [newPassword, t]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');

    const strengthError = validateNewPassword(newPassword, t);
    if (strengthError) {
      setError(strengthError);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t('auth.passwordMismatch'));
      return;
    }

    setLoading(true);
    try {
      const headers = typeof authHeaders === 'function' ? authHeaders() : (authHeaders || {});
      const r = await fetch(`${apiBaseUrl}/auth/me/password`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...headers
        },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!r.ok) {
        const payload = await r.json().catch(() => null);
        throw new Error((payload && (payload.detail || payload.message)) || `HTTP ${r.status}`);
      }
      onComplete();
    } catch (err) {
      setError(err.message || t('auth.passwordChangeFailed'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-ink bg-hero-gradient flex w-full">
      <div className="min-h-screen flex items-center justify-center w-full">
        <div className="max-w-md w-full mx-4">
          <div className="rounded-xl glassmorphism-strong p-6 space-y-4 animate-fade-in">
            <div className="text-center mb-2 animate-slide-up">
              <div className="w-16 h-16 bg-brand-500 rounded-full flex items-center justify-center mx-auto mb-4 shadow-card">
                <FaLock className="text-2xl text-white" />
              </div>
              <h1 className="text-2xl font-bold text-white">{appName}</h1>
              <p className="text-white/70 mt-2">{t('auth.passwordChangeRequired')}</p>
              <p className="text-xs text-white/50 mt-1">
                {t('auth.mustChangePassword')}
              </p>
            </div>

            {error && (
              <div className="bg-red-500/10 border border-red-500/20 text-red-300 p-3 rounded-lg text-sm animate-slide-up">
                {error}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4 animate-slide-up-delayed">
              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">{t('auth.currentPassword')}</label>
                <input
                  type="password"
                  className="w-full rounded-md bg-white/5 border border-white/10 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-brand-500 text-white placeholder-white/50"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">{t('auth.newPassword')}</label>
                <input
                  type="password"
                  className="w-full rounded-md bg-white/5 border border-white/10 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-brand-500 text-white placeholder-white/50"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                />
                {passwordHint && !error && (
                  <div className="text-xs text-white/50 mt-2">{passwordHint}</div>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-white/70 mb-2">{t('auth.confirmPassword')}</label>
                <input
                  type="password"
                  className="w-full rounded-md bg-white/5 border border-white/10 px-4 py-3 focus:outline-none focus:ring-2 focus:ring-brand-500 text-white placeholder-white/50"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full py-3 rounded-md bg-brand-500 hover:bg-brand-600 disabled:opacity-50 text-white font-medium transition-colors hover-lift"
              >
                {loading ? t('auth.updatingPassword') : t('auth.updatePassword')}
              </button>

              <button
                type="button"
                onClick={onLogout}
                className="w-full py-2 rounded-md bg-white/10 hover:bg-white/20 text-white/80 transition-colors"
              >
                {t('auth.logout')}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}
