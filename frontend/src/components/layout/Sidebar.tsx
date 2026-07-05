// ============================================
// Musically — Sidebar Component
// Desktop sidebar navigation with Cohere styling
// ============================================

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
} from 'lucide-react';

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
  { to: '/playlists', label: 'Playlists', icon: <ListMusic className="w-5 h-5" /> },
  { to: '/discover', label: 'Discover', icon: <Search className="w-5 h-5" /> },
  { to: '/tasks', label: 'Tasks', icon: <Timer className="w-5 h-5" /> },
  { to: '/logs', label: 'Logs', icon: <ScrollText className="w-5 h-5" /> },
  { to: '/database', label: 'Database', icon: <Database className="w-5 h-5" /> },
  { to: '/settings', label: 'Settings', icon: <Settings className="w-5 h-5" /> },
];

export function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-screen w-64 bg-primary text-on-dark flex flex-col z-30">
      {/* Logo */}
      <div className="px-6 py-8">
        <NavLink to="/" className="inline-block">
          <h1 className="font-display text-2xl tracking-tight text-white">
            Musically
          </h1>
        </NavLink>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-2">
        <ul className="space-y-1">
          {navItems.map((item) => (
            <li key={item.to}>
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-4 py-2.5 rounded-sm text-sm transition-colors duration-150 ${
                    isActive
                      ? 'bg-white/10 text-white border-l-[3px] border-coral pl-3.25'
                      : 'text-muted hover:bg-white/5 hover:text-white border-l-[3px] border-transparent pl-3.25'
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
        <div className="flex items-center gap-2 text-xs text-muted">
          <span className="coral-dot" />
          <span>v0.1.0</span>
        </div>
      </div>
    </aside>
  );
}
