import { Navigate, Route, Routes } from 'react-router-dom';
import { Navbar } from '@/components/layout/Navbar';
import { Footer } from '@/components/layout/Footer';
import { ConfigPage } from '@/pages/ConfigPage';
import { NewRunPage } from '@/pages/NewRunPage';
import { RunsListPage } from '@/pages/RunsListPage';
import { RunDetailPage } from '@/pages/RunDetailPage';

export default function App() {
  return (
    <div className="min-h-screen flex flex-col">
      <Navbar />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsListPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/runs" replace />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
