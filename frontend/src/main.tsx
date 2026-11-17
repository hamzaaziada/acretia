import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/ibm-plex-sans-arabic/arabic-400.css';
import '@fontsource/ibm-plex-sans-arabic/arabic-500.css';
import '@fontsource/ibm-plex-sans-arabic/arabic-600.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import './ds/tokens.css';
import './ds/base.css';
import './ds/components.css';
import './ds/extra.css';
import './app/app.css';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { I18nProvider, useI18n } from './i18n';
import { ToastProvider } from './ds';
import { AuthProvider } from './api/hooks';
import { ThemeProvider } from './app/theme';
import { App } from './app/App';

function Providers() {
  const { t } = useI18n();
  return (
    <ToastProvider dismissLabel={t('common.dismiss')}>
      <BrowserRouter>
        <AuthProvider>
          <ThemeProvider>
            <App />
          </ThemeProvider>
        </AuthProvider>
      </BrowserRouter>
    </ToastProvider>
  );
}

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <I18nProvider>
      <Providers />
    </I18nProvider>
  </StrictMode>,
);
