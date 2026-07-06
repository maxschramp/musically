// ============================================
// Musically — MobileNav Component
// Fixed bottom tab bar for mobile navigation
// Brand-styled with coral accent for active state
// ============================================

import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Heart,
  Compass,
  Download,
  Disc3,
} from 'lucide-react';

interface MobileNavItem {
  to: string;
  label: string;
  icon: React.ReactNode;
}

const mobileNavItems: MobileNavItem[] = [
  { to: '/', label: 'Home', icon: <LayoutDashboard className="w-5 h-5" /> },
  { to: '/swipe', label: 'Swipe', icon: <Heart className="w-5 h-5" /> },
  { to: '/downloads', label: 'Downloads', icon: <Download className="w-5 h-5" /> },
  { to: '/library', label: 'Library', icon: <Disc3 className="w-5 h-5" /> },
  { to: '/discover', label: 'Discover', icon: <Compass className="w-5 h-5" /> },
];

export function MobileNav() {
  return (
    <nav className="fixed bottom-0 left-0 right-0 bg-canvas border-t border-border-light z-30 safe-area-bottom">
      <ul className="flex items-center justify-around h-16 px-2">
        {mobileNavItems.map((item) => (
          <li key={item.to} className="flex-1">
            <NavLink
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center justify-center gap-0.5 py-1 text-xs transition-all duration-150 ${
                  isActive
                    ? 'text-brand-coral scale-105'
                    : 'text-muted hover:text-ink active:scale-95'
                }`
              }
            >
              {item.icon}
              <span className="text-[10px] font-medium">{item.label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
