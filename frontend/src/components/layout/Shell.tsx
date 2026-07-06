// ============================================
// Musically — Shell Component
// Main app shell: sidebar on desktop, bottom nav on mobile
// Includes dark mode toggle and SSE status indicator
// ============================================

import { Outlet, useLocation } from 'react-router-dom';
import { Sun, Moon } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { UpdateBanner } from '@/components/shared/UpdateBanner';
import { useIsMobile } from '@/hooks/useMediaQuery';
import { useEvents } from '@/hooks/useEvents';
import { useDarkMode } from '@/hooks/useDarkMode';

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
  const { isDark, toggleTheme } = useDarkMode();

  const currentTitle = pageTitles[location.pathname] ?? 'Musically';

  // Check if current route is a detail page
  const isDetailPage = location.pathname.split('/').length > 2;

  return (
    <div className="min-h-screen bg-off-white">
      <UpdateBanner />
      {isMobile ? (
        /* ============== Mobile Layout ============== */
        <div className="flex flex-col min-h-screen pb-16">
          {/* Mobile Header */}
          <header className="sticky top-0 z-20 bg-canvas border-b border-border-light px-4 py-3">
            <div className="flex items-center justify-between">
              <h1 className="font-display text-lg text-ink tracking-tight font-semibold">
                {currentTitle}
              </h1>
              <button
                onClick={toggleTheme}
                className="icon-chip icon-chip-sm icon-chip-grey hover:opacity-80 transition-opacity"
                aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
              </button>
            </div>
          </header>

          {/* Content */}
          <main className="flex-1 px-4 py-4">
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
                <div className="flex items-center gap-3">
                  {isDetailPage && (
                    <button
                      onClick={() => window.history.back()}
                      className="text-muted hover:text-ink transition-colors mr-1"
                      aria-label="Go back"
                    >
                      ←
                    </button>
                  )}
                  <h1 className="font-display text-xl text-ink tracking-tight font-semibold">
                    {currentTitle}
                  </h1>
                </div>
                <div className="flex items-center gap-3">
                  {/* Theme toggle */}
                  <button
                    onClick={toggleTheme}
                    className="icon-chip icon-chip-sm icon-chip-grey hover:opacity-80 transition-opacity"
                    aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
                  >
                    {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                  </button>
                  {/* SSE Status */}
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
