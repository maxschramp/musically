// ============================================
// Musically — Sidebar Component
// Desktop sidebar navigation with brand Dark Green styling
// Includes update-available indicator
// ============================================

import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  ListMusic,
  Heart,
  Download,
  Disc3,
  Users,
  Settings,
  Timer,
  ScrollText,
  Database,
  Search,
  Play,
  ArrowUpCircle,
} from 'lucide-react';
import { useApiQuery } from '@/hooks/useApi';

interface NavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const navItems: NavItem[] = [
  { to: '/', label: 'Dashboard', icon: <LayoutDashboard className="w-5 h-5" /> },
  { to: '/queue', label: 'Queue', icon: <ListMusic className="w-5 h-5" /> },
  { to: '/downloads', label: 'Downloads', icon: <Download className="w-5 h-5" /> },
  { to: '/swipe', label: 'Swipe', icon: <Heart className="w-5 h-5" /> },
  { to: '/library', label: 'Library', icon: <Disc3 className="w-5 h-5" /> },
  { to: '/artists', label: 'Artists', icon: <Users className="w-5 h-5" /> },
  { to: '/playlists', label: 'Playlists', icon: <Play className="w-5 h-5" /> },
  { to: '/discover', label: 'Discover', icon: <Search className="w-5 h-5" /> },
  { to: '/tasks', label: 'Tasks', icon: <Timer className="w-5 h-5" /> },
  { to: '/logs', label: 'Logs', icon: <ScrollText className="w-5 h-5" /> },
  { to: '/database', label: 'Database', icon: <Database className="w-5 h-5" /> },
  { to: '/settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
];

export function Sidebar() {
  const [showVersionTooltip, setShowVersionTooltip] = useState(false);

  const { data: versionInfo } = useApiQuery<{ version: string; build_date: string; build_ref: string }>(
    ['version'],
    '/health/version',
    undefined,
    { staleTime: 300_000, refetchOnWindowFocus: false },
  );

  // Check if update is available (simple semver comparison against a hardcoded latest)
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [latestVersion, setLatestVersion] = useState<string | null>(null);

  // Poll for updates every 30 min
  useState(() => {
    const checkUpdate = async () => {
      try {
        const resp = await fetch('https://api.github.com/repos/musically-app/musically/releases/latest');
        if (resp.ok) {
          const release = await resp.json();
          const latest = release.tag_name?.replace(/^v/, '');
          if (latest && versionInfo?.version && latest > versionInfo.version) {
            setUpdateAvailable(true);
            setLatestVersion(latest);
          }
        }
      } catch {
        // Silently fail — GitHub may be unreachable
      }
    };
    checkUpdate();
    const interval = setInterval(checkUpdate, 1_800_000); // 30 min
    return () => clearInterval(interval);
  });

  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-brand-dark text-on-dark flex flex-col z-30">
      {/* Logo */}
      <div className="px-6 py-8">
        <NavLink to="/" className="inline-flex items-center gap-3 group">
          {/* Brand icon — waveform + play + stack */}
          <svg width="32" height="37" viewBox="0 0 58.17 67.23" className="shrink-0" aria-label="Musically logo">
            <path fill="#4B6E55" d="M47.66 20.05l10.25.07c-1.2 8.31-8.55 14.69-17.19 14.66l-24.63-.1c-8.25-.03-14.72-6.71-15.94-14.57l11.89-.04c2.7 0 4.83-1.5 5.73-3.96l2.14-5.85c.25-.67.71-.96 1.23-.98.67-.02 1.09.38 1.36 1.28l4.49 14.75c.63 2.06 2.29 3.35 4.18 3.59 2.05.26 3.96-1.2 4.69-3.42l2.95-9c.27-.84.94-1.37 1.57-1.43 1.98-.17 2.57 4.97 7.27 5z"/>
            <path fill="#4B6E55" d="M32.86 24.2c-.27.8-.86 1.41-1.22 1.51-3.36.86-3.75-20.07-10.51-19.77-5.02.22-4.36 6.49-7.53 10.76L.01 16.83C.47 7.78 7.68.18 16.97.13L39.38 0c10.01-.06 18.31 6.94 18.67 16.83l-10.58-.06c-2.33-.01-2.94-5.16-7.1-5.18-2.02 0-3.71 1.29-4.43 3.41l-3.09 9.19z" opacity=".85"/>
            <path fill="#A57DCD" d="M52.27 42.73c-.44 2.38 1.54 2.84 2.8 4.78l-20.38.16c-2.29.02-3.71-2.42-3.66-4.17.07-2.34 1.8-4.18 4.37-4.18l19.57.06-2.7 3.33zM53.74 57.3l-19.18-.3c1.43-1.46 2.36-2.41 2.42-3.62.07-1.47-.78-2.39-2.07-4.15l19.16-.18c2.41-.02 3.9 1.89 4.08 3.72.23 2.43-1.36 4.57-4.4 4.52zM54.81 66.85l-19.41.19c-2.11.02-3.66-1.55-4.01-3.08-.4-1.74.42-4.81 2.71-4.82l20.78-.06c-1.49 1.59-2.69 2.43-2.72 3.66-.04 1.63.93 2.16 2.65 4.11z"/>
            <path fill="#FF7F6E" d="M28.22 53.17c0 7.76-6.29 14.06-14.06 14.06S.11 60.94.11 53.17s6.29-14.06 14.06-14.06 14.06 6.29 14.06 14.06zm-7.11-.16l-10.52-6.27.06 12.62c3.9-1.98 7.16-3.48 10.46-6.35z"/>
          </svg>
          <h1 className="font-display text-2xl tracking-tight text-white font-semibold group-hover:opacity-80 transition-opacity lowercase">
            musically
          </h1>
        </NavLink>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-2 overflow-y-auto">
        <ul className="space-y-1">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-pill text-sm transition-colors duration-150 ${
                    isActive
                      ? 'bg-white/15 text-white font-medium'
                      : 'text-white/60 hover:bg-white/8 hover:text-white'
                  }`
                }
              >
                {item.icon}
                <span>{item.label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-white/10">
        <div
          className="relative inline-flex items-center gap-2 text-xs text-white/55 cursor-default"
          onMouseEnter={() => setShowVersionTooltip(true)}
          onMouseLeave={() => setShowVersionTooltip(false)}
        >
          <span className="coral-dot" />
          <span>v{versionInfo?.version ?? '...'}</span>

          {/* Update Available Indicator */}
          {updateAvailable && latestVersion && (
            <span className="relative flex items-center gap-1 ml-1">
              <ArrowUpCircle className="w-3.5 h-3.5 text-brand-coral animate-pulse" />
              <span className="text-[10px] font-medium text-brand-coral">
                v{latestVersion}
              </span>
            </span>
          )}

          {/* Tooltip */}
          {showVersionTooltip && (
            <div className="absolute bottom-full left-0 mb-2 w-56 px-3 py-2 rounded-sm bg-[#1a2a1f] text-[11px] text-white/60 leading-relaxed shadow-lg border border-white/10 z-50">
              {versionInfo ? (
                <>
                  <div className="flex justify-between">
                    <span className="text-white/50">Version</span>
                    <span className="text-white font-mono">{versionInfo.version}</span>
                  </div>
                  <div className="flex justify-between mt-1">
                    <span className="text-white/50">Built</span>
                  <span className="text-white font-mono">{versionInfo.build_date}</span>
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-white/50">Ref</span>
                  <span className="text-white font-mono text-[10px]">{versionInfo.build_ref}</span>
                </div>
              </>
            ) : (
              <span>Loading version info&hellip;</span>
            )}
            {updateAvailable && latestVersion && (
              <div className="mt-2 pt-2 border-t border-white/10">
                <p className="text-brand-coral font-medium">
                  ⬆ Update available: v{latestVersion}
                </p>
              </div>
            )}
          </div>
          )}
        </div>
      </div>
    </aside>
  );
}
