// ============================================
// Musically — Shell Component
// Main app shell: sidebar on desktop, bottom nav on mobile
// ============================================

import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useEvents } from '@/hooks/useEvents';

const pageTitles: Record<string, string> = {
  '/': 'Dashboard',
  '/queue': 'Queue',
  '/swipe': 'Swipe',
  '/downloads': 'Downloads',
  '/library': 'Library',
  '/artists': 'Artists',
  '/playlists': 'Playlists',
  '/settings': 'Settings',
  '/tasks': 'Tasks',
  '/logs': 'Logs',
  '/database': 'Database',
  '/discover': 'Discover',
};

export function Shell() {
  const isMobile = useIsMobile();
  const location = useLocation();
  const { isConnected } = useEvents();

  const currentTitle = pageTitles[location.pathname] ?? 'Musically';

  return (
    <div className="min-h-screen bg-[#fafafa]">
      {isMobile ? (
        /* ============== Mobile Layout ============== */
        <div className="flex flex-col min-h-screen pb-16">
          {/* Mobile Header */}
          <header className="sticky top-0 z-20 bg-canvas border-b border-border-light px-4 py-3">
            <h1 className="font-display text-lg text-ink tracking-tight">
              {currentTitle}
            </h1>
          </header>

          {/* Content */}
          <main className="flex-1">
            <Outlet />
          </main>

          <MobileNav />
        </div>
      ) : (
        /* ============== Desktop Layout ============== */
        <div className="flex min-h-screen">
          <Sidebar />

          <div className="flex-1 ml-64 flex flex-col min-h-screen">
            {/* Desktop Header Bar */}
            <header className="sticky top-0 z-20 bg-canvas border-b border-border-light px-8 py-4">
              <div className="flex items-center justify-between">
                <h1 className="font-display text-xl text-ink tracking-tight">
                  {currentTitle}
                </h1>
                <div className="flex items-center gap-3">
                  <span
                    className={isConnected ? 'coral-dot' : 'muted-dot'}
                    title={isConnected ? 'Live — SSE Connected' : 'SSE Disconnected'}
                  />
                  <span className="text-xs text-muted">
                    Musically
                  </span>
                </div>
              </div>
            </header>

            {/* Content */}
            <main className="flex-1 p-8">
              <Outlet />
            </main>
          </div>
        </div>
      )}
    </div>
  );
}
