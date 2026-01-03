import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useTranslation, SUPPORTED_LANGUAGES } from './I18nContext';
import { FiGlobe, FiCheck, FiChevronDown } from 'react-icons/fi';

/**
 * LanguageSwitcher Component
 * 
 * A dropdown component for selecting the application language.
 * Features:
 * - Shows current language with flag and name
 * - Dropdown with all supported languages
 * - Search/filter functionality for languages
 * - Compact mode for sidebar/header use
 * - Full mode for settings page
 */

const LanguageSwitcher = ({ 
  variant = 'dropdown', // 'dropdown' | 'select' | 'minimal'
  showLabel = true,
  className = '',
  dropdownPosition = 'bottom-left', // 'bottom-left' | 'bottom-right' | 'top-left' | 'top-right'
}) => {
  const { language, setLanguage, t } = useTranslation();
  const [isOpen, setIsOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const dropdownRef = useRef(null);
  const searchInputRef = useRef(null);

  // Convert SUPPORTED_LANGUAGES object to array with code property
  const languagesArray = useMemo(() => 
    Object.entries(SUPPORTED_LANGUAGES).map(([code, info]) => ({
      code,
      ...info
    })), 
  []);

  // Find current language info
  const currentLang = languagesArray.find(l => l.code === language) || languagesArray[0];

  // Filter languages based on search
  const filteredLanguages = languagesArray.filter(lang => 
    lang.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    lang.nativeName.toLowerCase().includes(searchTerm.toLowerCase()) ||
    lang.code.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
        setSearchTerm('');
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Focus search input when dropdown opens
  useEffect(() => {
    if (isOpen && searchInputRef.current) {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      setIsOpen(false);
      setSearchTerm('');
    }
  };

  const handleLanguageSelect = (langCode) => {
    setLanguage(langCode);
    setIsOpen(false);
    setSearchTerm('');
  };

  // Position classes for dropdown
  const positionClasses = {
    'bottom-left': 'top-full left-0 mt-1',
    'bottom-right': 'top-full right-0 mt-1',
    'top-left': 'bottom-full left-0 mb-1',
    'top-right': 'bottom-full right-0 mb-1',
  };

  // Minimal variant - just an icon button
  if (variant === 'minimal') {
    return (
      <div className={`relative ${className}`} ref={dropdownRef}>
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="p-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
          title={t('common.language')}
          aria-label={t('common.selectLanguage')}
        >
          <span className="text-lg">{currentLang.flag}</span>
        </button>

        {isOpen && (
          <div 
            className={`absolute ${positionClasses[dropdownPosition]} z-50 w-64 max-h-80 overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700`}
            onKeyDown={handleKeyDown}
          >
            <div className="p-2 border-b border-gray-200 dark:border-gray-700">
              <input
                ref={searchInputRef}
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder={t('common.search')}
                className="w-full px-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 border-0 rounded-md focus:ring-2 focus:ring-blue-500 dark:text-white"
              />
            </div>
            <div className="max-h-60 overflow-y-auto">
              {filteredLanguages.map((lang) => (
                <button
                  key={lang.code}
                  onClick={() => handleLanguageSelect(lang.code)}
                  className={`w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors ${
                    lang.code === language ? 'bg-blue-50 dark:bg-blue-900/30' : ''
                  }`}
                >
                  <span className="text-lg">{lang.flag}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 dark:text-white truncate">
                      {lang.nativeName}
                    </div>
                    <div className="text-xs text-gray-500 dark:text-gray-400 truncate">
                      {lang.name}
                    </div>
                  </div>
                  {lang.code === language && (
                    <FiCheck className="w-4 h-4 text-blue-500" />
                  )}
                </button>
              ))}
              {filteredLanguages.length === 0 && (
                <div className="px-3 py-4 text-sm text-gray-500 dark:text-gray-400 text-center">
                  {t('errors.notFound')}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  // Select variant - native select element
  if (variant === 'select') {
    return (
      <div className={`flex items-center gap-2 ${className}`}>
        {showLabel && (
          <label className="text-sm font-medium text-gray-700 dark:text-gray-300">
            <FiGlobe className="inline-block mr-1" />
            {t('common.language')}
          </label>
        )}
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="px-3 py-2 text-sm bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 dark:text-white"
        >
          {languagesArray.map((lang) => (
            <option key={lang.code} value={lang.code}>
              {lang.flag} {lang.nativeName} ({lang.name})
            </option>
          ))}
        </select>
      </div>
    );
  }

  // Default dropdown variant
  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-2 text-sm bg-white dark:bg-gray-700 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
        aria-label={t('common.selectLanguage')}
        aria-expanded={isOpen}
      >
        <span className="text-lg">{currentLang.flag}</span>
        {showLabel && (
          <span className="text-gray-700 dark:text-gray-200">
            {currentLang.nativeName}
          </span>
        )}
        <FiChevronDown className={`w-4 h-4 text-gray-500 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div 
          className={`absolute ${positionClasses[dropdownPosition]} z-50 w-72 max-h-96 overflow-hidden bg-white dark:bg-gray-800 rounded-lg shadow-xl border border-gray-200 dark:border-gray-700`}
          onKeyDown={handleKeyDown}
        >
          <div className="p-3 border-b border-gray-200 dark:border-gray-700">
            <div className="relative">
              <FiGlobe className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                ref={searchInputRef}
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder={t('common.search')}
                className="w-full pl-9 pr-3 py-2 text-sm bg-gray-100 dark:bg-gray-700 border-0 rounded-lg focus:ring-2 focus:ring-blue-500 dark:text-white"
              />
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto p-1">
            {filteredLanguages.map((lang) => (
              <button
                key={lang.code}
                onClick={() => handleLanguageSelect(lang.code)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 text-left rounded-md hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors ${
                  lang.code === language ? 'bg-blue-50 dark:bg-blue-900/30 ring-1 ring-blue-200 dark:ring-blue-800' : ''
                }`}
              >
                <span className="text-xl">{lang.flag}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-gray-900 dark:text-white">
                    {lang.nativeName}
                  </div>
                  <div className="text-xs text-gray-500 dark:text-gray-400">
                    {lang.name}
                  </div>
                </div>
                {lang.code === language && (
                  <FiCheck className="w-5 h-5 text-blue-500 flex-shrink-0" />
                )}
              </button>
            ))}
            {filteredLanguages.length === 0 && (
              <div className="px-3 py-6 text-sm text-gray-500 dark:text-gray-400 text-center">
                {t('errors.notFound')}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

/**
 * LanguageSwitcherCompact
 * 
 * A compact version for use in tight spaces like the sidebar
 */
export const LanguageSwitcherCompact = ({ className = '' }) => {
  return (
    <LanguageSwitcher 
      variant="minimal" 
      showLabel={false}
      className={className}
      dropdownPosition="top-right"
    />
  );
};

/**
 * LanguageSwitcherFull
 * 
 * A full version for use in settings pages
 */
export const LanguageSwitcherFull = ({ className = '' }) => {
  const { t } = useTranslation();
  
  return (
    <div className={`space-y-2 ${className}`}>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
        {t('settings.language')}
      </label>
      <LanguageSwitcher 
        variant="dropdown" 
        showLabel={true}
        dropdownPosition="bottom-left"
      />
    </div>
  );
};

export default LanguageSwitcher;
