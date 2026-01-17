import React from 'react';
import { FaExclamationTriangle, FaTimes } from 'react-icons/fa';
import { useTranslation } from '../i18n';

/**
 * ConfirmModal - A styled confirmation dialog to replace browser's default confirm()
 * 
 * Props:
 * - isOpen: boolean - Whether the modal is visible
 * - title: string - Modal title
 * - message: string - Main message/description
 * - confirmText: string - Text for confirm button (default: "Confirm")
 * - cancelText: string - Text for cancel button (default: "Cancel")
 * - confirmVariant: "danger" | "warning" | "primary" - Button style (default: "danger")
 * - onConfirm: () => void - Called when user confirms
 * - onCancel: () => void - Called when user cancels
 * - isLoading: boolean - Show loading state on confirm button
 */
export default function ConfirmModal({
    isOpen,
    title = 'Confirm Action',
    message = 'Are you sure you want to proceed?',
    confirmText = 'Confirm',
    cancelText = 'Cancel',
    confirmVariant = 'danger',
    onConfirm,
    onCancel,
    isLoading = false,
}) {
    if (!isOpen) return null;

    const variantStyles = {
        danger: 'bg-red-600 hover:bg-red-500 focus:ring-red-500',
        warning: 'bg-orange-600 hover:bg-orange-500 focus:ring-orange-500',
        primary: 'bg-brand-600 hover:bg-brand-500 focus:ring-brand-500',
    };

    const buttonStyle = variantStyles[confirmVariant] || variantStyles.danger;

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
            {/* Backdrop */}
            <div
                className="absolute inset-0 bg-black/70 backdrop-blur-sm"
                onClick={onCancel}
            />

            {/* Modal */}
            <div className="relative bg-ink-900 border border-white/10 rounded-2xl shadow-2xl max-w-md w-full mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
                {/* Header */}
                <div className="flex items-center justify-between p-5 border-b border-white/10">
                    <div className="flex items-center gap-3">
                        <div className={`w-10 h-10 rounded-full flex items-center justify-center ${confirmVariant === 'danger' ? 'bg-red-500/20 text-red-400' :
                            confirmVariant === 'warning' ? 'bg-orange-500/20 text-orange-400' :
                                'bg-brand-500/20 text-brand-400'
                            }`}>
                            <FaExclamationTriangle className="text-lg" />
                        </div>
                        <h2 className="text-lg font-semibold text-white">{title}</h2>
                    </div>
                    <button
                        onClick={onCancel}
                        className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                    >
                        <FaTimes />
                    </button>
                </div>

                {/* Body */}
                <div className="p-5">
                    <p className="text-white/70 leading-relaxed">{message}</p>
                </div>

                {/* Footer */}
                <div className="flex justify-end gap-3 p-5 pt-0">
                    <button
                        onClick={onCancel}
                        disabled={isLoading}
                        className="px-5 py-2.5 text-white/70 hover:text-white hover:bg-white/10 rounded-lg transition-colors font-medium disabled:opacity-50"
                    >
                        {cancelText}
                    </button>
                    <button
                        onClick={onConfirm}
                        disabled={isLoading}
                        className={`px-5 py-2.5 text-white rounded-lg transition-colors font-medium flex items-center gap-2 disabled:opacity-50 focus:ring-2 focus:ring-offset-2 focus:ring-offset-ink-900 ${buttonStyle}`}
                    >
                        {isLoading && (
                            <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        )}
                        {confirmText}
                    </button>
                </div>
            </div>
        </div>
    );
}
