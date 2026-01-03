import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';

// Supported languages with their display names and flags
export const SUPPORTED_LANGUAGES = {
  en: { name: 'English', nativeName: 'English', flag: '🇬🇧' },
  de: { name: 'German', nativeName: 'Deutsch', flag: '🇩🇪' },
  es: { name: 'Spanish', nativeName: 'Español', flag: '🇪🇸' },
  fr: { name: 'French', nativeName: 'Français', flag: '🇫🇷' },
  it: { name: 'Italian', nativeName: 'Italiano', flag: '🇮🇹' },
  pt: { name: 'Portuguese', nativeName: 'Português', flag: '🇵🇹' },
  ru: { name: 'Russian', nativeName: 'Русский', flag: '🇷🇺' },
  zh: { name: 'Chinese', nativeName: '中文', flag: '🇨🇳' },
  ja: { name: 'Japanese', nativeName: '日本語', flag: '🇯🇵' },
  ko: { name: 'Korean', nativeName: '한국어', flag: '🇰🇷' },
  pl: { name: 'Polish', nativeName: 'Polski', flag: '🇵🇱' },
  nl: { name: 'Dutch', nativeName: 'Nederlands', flag: '🇳🇱' },
  tr: { name: 'Turkish', nativeName: 'Türkçe', flag: '🇹🇷' },
  ar: { name: 'Arabic', nativeName: 'العربية', flag: '🇸🇦', rtl: true },
  sv: { name: 'Swedish', nativeName: 'Svenska', flag: '🇸🇪' },
  da: { name: 'Danish', nativeName: 'Dansk', flag: '🇩🇰' },
  no: { name: 'Norwegian', nativeName: 'Norsk', flag: '🇳🇴' },
  fi: { name: 'Finnish', nativeName: 'Suomi', flag: '🇫🇮' },
  cs: { name: 'Czech', nativeName: 'Čeština', flag: '🇨🇿' },
  uk: { name: 'Ukrainian', nativeName: 'Українська', flag: '🇺🇦' },
  hu: { name: 'Hungarian', nativeName: 'Magyar', flag: '🇭🇺' },
  ro: { name: 'Romanian', nativeName: 'Română', flag: '🇷🇴' },
  el: { name: 'Greek', nativeName: 'Ελληνικά', flag: '🇬🇷' },
  th: { name: 'Thai', nativeName: 'ไทย', flag: '🇹🇭' },
  vi: { name: 'Vietnamese', nativeName: 'Tiếng Việt', flag: '🇻🇳' },
  id: { name: 'Indonesian', nativeName: 'Bahasa Indonesia', flag: '🇮🇩' },
  hi: { name: 'Hindi', nativeName: 'हिन्दी', flag: '🇮🇳' },
};

const I18N_STORAGE_KEY = 'lynx-language';
const DEFAULT_LANGUAGE = 'en';

// Create context
const I18nContext = createContext(null);

// Lazy load translations
const translationCache = {};

async function loadTranslations(lang) {
  if (translationCache[lang]) {
    return translationCache[lang];
  }
  
  try {
    const module = await import(`./locales/${lang}.js`);
    translationCache[lang] = module.default || module;
    return translationCache[lang];
  } catch (error) {
    console.warn(`Failed to load translations for ${lang}, falling back to English:`, error);
    if (lang !== DEFAULT_LANGUAGE) {
      return loadTranslations(DEFAULT_LANGUAGE);
    }
    return {};
  }
}

// Get initial language from storage or browser
function getInitialLanguage() {
  if (typeof window === 'undefined') return DEFAULT_LANGUAGE;
  
  // Check localStorage first
  const stored = localStorage.getItem(I18N_STORAGE_KEY);
  if (stored && SUPPORTED_LANGUAGES[stored]) {
    return stored;
  }
  
  // Try browser language
  const browserLang = navigator.language?.split('-')[0];
  if (browserLang && SUPPORTED_LANGUAGES[browserLang]) {
    return browserLang;
  }
  
  return DEFAULT_LANGUAGE;
}

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(getInitialLanguage);
  const [translations, setTranslations] = useState({});
  const [isLoading, setIsLoading] = useState(true);

  // Load translations when language changes
  useEffect(() => {
    let cancelled = false;
    
    async function load() {
      setIsLoading(true);
      const trans = await loadTranslations(language);
      if (!cancelled) {
        setTranslations(trans);
        setIsLoading(false);
        
        // Update document direction for RTL languages
        const langConfig = SUPPORTED_LANGUAGES[language];
        if (langConfig?.rtl) {
          document.documentElement.setAttribute('dir', 'rtl');
        } else {
          document.documentElement.setAttribute('dir', 'ltr');
        }
      }
    }
    
    load();
    return () => { cancelled = true; };
  }, [language]);

  // Set language and persist
  const setLanguage = useCallback((lang) => {
    if (!SUPPORTED_LANGUAGES[lang]) {
      console.warn(`Unsupported language: ${lang}`);
      return;
    }
    setLanguageState(lang);
    if (typeof window !== 'undefined') {
      localStorage.setItem(I18N_STORAGE_KEY, lang);
    }
  }, []);

  // Translation function with interpolation support
  const t = useCallback((key, params = {}) => {
    // Get nested value by dot notation
    const keys = key.split('.');
    let value = translations;
    
    for (const k of keys) {
      if (value && typeof value === 'object' && k in value) {
        value = value[k];
      } else {
        // Return key as fallback
        return key;
      }
    }
    
    if (typeof value !== 'string') {
      return key;
    }
    
    // Replace placeholders like {{name}} with params
    return value.replace(/\{\{(\w+)\}\}/g, (match, paramKey) => {
      return params[paramKey] !== undefined ? String(params[paramKey]) : match;
    });
  }, [translations]);

  const value = useMemo(() => ({
    language,
    setLanguage,
    t,
    isLoading,
    isRTL: SUPPORTED_LANGUAGES[language]?.rtl || false,
    languageConfig: SUPPORTED_LANGUAGES[language] || SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE],
  }), [language, setLanguage, t, isLoading]);

  return (
    <I18nContext.Provider value={value}>
      {children}
    </I18nContext.Provider>
  );
}

// Hook to use translations
export function useTranslation() {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useTranslation must be used within an I18nProvider');
  }
  return context;
}

// Hook for just the t function (convenience)
export function useT() {
  const { t } = useTranslation();
  return t;
}

// Export the context for advanced use cases
export { I18nContext };

export default I18nContext;
