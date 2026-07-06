// ============================================
// Musically — App Component
// React Router v6 routes with Shell layout + Error Boundaries
// ============================================

import { Routes, Route, Navigate } from 'react-router-dom';
import { Shell } from '@/components/layout/Shell';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { Dashboard } from '@/pages/Dashboard';
import { Queue } from '@/pages/Queue';
import { Swipe } from '@/pages/Swipe';
import { Downloads } from '@/pages/Downloads';
import { Library } from '@/pages/Library';
import { Artists } from '@/pages/Artists';
import { AlbumDetail } from '@/pages/AlbumDetail';
import { ArtistDetail } from '@/pages/ArtistDetail';
import { Playlists } from '@/pages/Playlists';
import { Settings } from '@/pages/Settings';
import { Tasks } from '@/pages/Tasks';
import { Logs } from '@/pages/Logs';
import { Database } from '@/pages/Database';
import { Discover } from '@/pages/Discover';

function PageWithErrorBoundary({ children }: { children: React.ReactNode }) {
  return <ErrorBoundary>{children}</ErrorBoundary>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<PageWithErrorBoundary><Dashboard /></PageWithErrorBoundary>} />
        <Route path="/queue" element={<PageWithErrorBoundary><Queue /></PageWithErrorBoundary>} />
        <Route path="/swipe" element={<PageWithErrorBoundary><Swipe /></PageWithErrorBoundary>} />
        <Route path="/downloads" element={<PageWithErrorBoundary><Downloads /></PageWithErrorBoundary>} />
        <Route path="/library" element={<PageWithErrorBoundary><Library /></PageWithErrorBoundary>} />
        <Route path="/library/:id" element={<PageWithErrorBoundary><AlbumDetail /></PageWithErrorBoundary>} />
        <Route path="/artists" element={<PageWithErrorBoundary><Artists /></PageWithErrorBoundary>} />
        <Route path="/artists/:id" element={<PageWithErrorBoundary><ArtistDetail /></PageWithErrorBoundary>} />
        <Route path="/playlists" element={<PageWithErrorBoundary><Playlists /></PageWithErrorBoundary>} />
        <Route path="/settings" element={<PageWithErrorBoundary><Settings /></PageWithErrorBoundary>} />
        <Route path="/tasks" element={<PageWithErrorBoundary><Tasks /></PageWithErrorBoundary>} />
        <Route path="/logs" element={<PageWithErrorBoundary><Logs /></PageWithErrorBoundary>} />
        <Route path="/database" element={<PageWithErrorBoundary><Database /></PageWithErrorBoundary>} />
        <Route path="/discover" element={<PageWithErrorBoundary><Discover /></PageWithErrorBoundary>} />
      </Route>

      {/* 404 catch-all — redirect to Dashboard */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
