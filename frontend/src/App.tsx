import { Navigate, Route, Routes } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Navbar } from '@/components/layout/Navbar';
import { ConfigPage } from '@/pages/ConfigPage';
import { PlaceholderPage } from '@/pages/PlaceholderPage';

export default function App() {
  const { t } = useTranslation();

  return (
    <div className="min-h-screen">
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<PlaceholderPage title={t('nav.runs')} />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/runs" replace />} />
        </Routes>
      </main>
    </div>
  );
}
