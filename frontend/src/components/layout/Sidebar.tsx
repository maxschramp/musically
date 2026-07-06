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
          {/* Brand icon */}
          <svg width="32" height="32" viewBox="0 0 58 58" fill="none" className="shrink-0">
            <rect width="58" height="58" rx="12" fill="#4B6E55"/>
            <g transform="translate(4,4) scale(0.86)">
              <path d="M47.66 20h5c-1.2 8-8.5 14-17 14H11c-8 0-14-6.5-15-14h12c2.5 0 4.5-1.5 5.5-4l2-6c.5-1 1.5-1 2 0l4.5 14.5c.5 2 2 3.5 4 3.5 2 0 4-1 4.5-3l3-9c.5-1 1.5-1.5 2-1.5 2 0 2.5 5 7 5Z" fill="#fff"/>
              <path d="M33 24c-.5 1-1 1.5-1.5 1.5-3.5 1-3.5-20-10.5-19.5-5 .2-4 6.5-7.5 10.5H0C.5 7.5 7.5 0 17 0h22.5c10 0 18 7 18.5 17h-10.5c-2.5 0-3-5-7-5-2 0-3.5 1.5-4.5 3.5l-3 8.5Z" fill="#fff" opacity=".7"/>
            </g>
          </svg>
          <h1 className="font-display text-2xl tracking-tight text-white font-semibold group-hover:opacity-80 transition-opacity">
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
