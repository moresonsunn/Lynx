import React, { createContext, useContext, useState, useCallback } from 'react';
import { FaCheckCircle, FaExclamationCircle, FaInfoCircle, FaTimes } from 'react-icons/fa';

const ToastContext = createContext();

// Toast notification component
function Toast({ toast, onClose }) {
  if (!toast) return null;

  const icons = {
    success: <FaCheckCircle className="text-green-400" />,
    error: <FaExclamationCircle className="text-red-400" />,
    info: <FaInfoCircle className="text-blue-400" />,
  };

  const bgColors = {
    success: 'bg-green-500/10 border-green-500/20',
    error: 'bg-red-500/10 border-red-500/20',
    info: 'bg-blue-500/10 border-blue-500/20',
  };

  return (
    <div className="fixed bottom-4 right-4 z-[9999] animate-fade-in">
      <div className={`flex items-center gap-3 px-4 py-3 rounded-lg border backdrop-blur-lg shadow-lg ${bgColors[toast.type] || bgColors.info}`}>
        <span className="text-lg">{icons[toast.type] || icons.info}</span>
        <span className="text-white text-sm font-medium max-w-xs">{toast.message}</span>
        <button
          onClick={onClose}
          className="ml-2 text-white/60 hover:text-white transition-colors"
        >
          <FaTimes />
        </button>
      </div>
    </div>
  );
}

// Toast provider
export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null);
  const [timeoutId, setTimeoutId] = useState(null);

  const showToast = useCallback((type, message, duration = 4000) => {
    // Clear any existing timeout
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    
    setToast({ type, message });
    
    // Auto-dismiss
    const id = setTimeout(() => {
      setToast(null);
    }, duration);
    setTimeoutId(id);
  }, [timeoutId]);

  const hideToast = useCallback(() => {
    if (timeoutId) {
      clearTimeout(timeoutId);
    }
    setToast(null);
  }, [timeoutId]);

  return (
    <ToastContext.Provider value={{ showToast, hideToast }}>
      {children}
      <Toast toast={toast} onClose={hideToast} />
    </ToastContext.Provider>
  );
}

// Hook to use toast
export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within ToastProvider');
  }
  return context;
}

export default ToastProvider;
