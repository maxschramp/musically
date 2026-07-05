// ============================================
// Musically — App Component
// React Router v6 routes with Shell layout
// ============================================

import { Routes, Route, Navigate } from 'react-router-dom';
import { Shell } from '@/components/layout/Shell';
import { Dashboard } from '@/pages/Dashboard';
import { Queue } from '@/pages/Queue';
import { Swipe } from '@/pages/Swipe';
import { Downloads } from '@/pages/Downloads';
import { Library } from '@/pages/Library';
import { Artists } from '@/pages/Artists';
import { Playlists } from '@/pages/Playlists';
import { Settings } from '@/pages/Settings';
import { Tasks } from '@/pages/Tasks';
import { Logs } from '@/pages/Logs';
import { Database } from '@/pages/Database';
import { Discover } from '@/pages/Discover';

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/queue" element={<Queue />} />
        <Route path="/swipe" element={<Swipe />} />
        <Route path="/downloads" element={<Downloads />} />
        <Route path="/library" element={<Library />} />
        <Route path="/artists" element={<Artists />} />
        <Route path="/playlists" element={<Playlists />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/database" element={<Database />} />
        <Route path="/discover" element={<Discover />} />
      </Route>

      {/* 404 catch-all — redirect to Dashboard */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
