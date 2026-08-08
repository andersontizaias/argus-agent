import { Navigate, Route, Routes } from 'react-router-dom';
import { Navbar } from '@/components/layout/Navbar';
import { ConfigPage } from '@/pages/ConfigPage';
import { NewRunPage } from '@/pages/NewRunPage';
import { RunsListPage } from '@/pages/RunsListPage';
import { RunDetailPage } from '@/pages/RunDetailPage';

export default function App() {
  return (
    <div className="min-h-screen">
      <Navbar />
      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsListPage />} />
          <Route path="/runs/new" element={<NewRunPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="*" element={<Navigate to="/runs" replace />} />
        </Routes>
      </main>
    </div>
  );
}
