import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import ptBR from '@/locales/pt-BR.json';
import enUS from '@/locales/en-US.json';

// pt-BR é o default (pedido explícito do usuário) — en-US é opt-in, não
// autodetectado do navegador (mesma convenção do useTheme.ts, chaveada em
// idioma em vez de tema).
export const STORAGE_KEY = 'argus-language';

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      'pt-BR': { translation: ptBR },
      'en-US': { translation: enUS },
    },
    fallbackLng: 'pt-BR',
    supportedLngs: ['pt-BR', 'en-US'],
    detection: {
      order: ['localStorage'],
      lookupLocalStorage: STORAGE_KEY,
      caches: ['localStorage'],
    },
    interpolation: { escapeValue: false },
  });

export default i18n;
