// ============================================
// Musically — Button Component
// Brand-styled: pill shapes, coral primary, dark green secondary
// Matches brand-guidelines.md §4.2
// ============================================

import { type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'accent' | 'ghost' | 'danger' | 'outline';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const variantClasses: Record<string, string> = {
  primary:
    'bg-brand-coral text-white hover:bg-[#e87262] active:bg-[#d46556] focus-visible:ring-2 focus-visible:ring-brand-coral focus-visible:ring-offset-2',
  secondary:
    'bg-brand-dark text-white hover:bg-[#3a5342] active:bg-[#253a2c] focus-visible:ring-2 focus-visible:ring-brand-dark focus-visible:ring-offset-2',
  accent:
    'bg-brand-purple text-white hover:bg-[#946fba] active:bg-[#8460aa] focus-visible:ring-2 focus-visible:ring-brand-purple focus-visible:ring-offset-2',
  outline:
    'bg-transparent text-brand-dark border border-brand-dark/30 hover:bg-brand-dark/5 active:bg-brand-dark/10 focus-visible:ring-2 focus-visible:ring-brand-dark focus-visible:ring-offset-2',
  ghost:
    'bg-transparent text-ink hover:bg-light-grey/50 active:bg-light-grey focus-visible:ring-2 focus-visible:ring-focus-blue focus-visible:ring-offset-2',
  danger:
    'bg-red-600 text-white hover:bg-red-700 active:bg-red-800 focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2',
};

const sizeClasses: Record<string, string> = {
  sm: 'px-3 py-1.5 text-sm gap-1.5 rounded-pill',
  md: 'px-6 py-2.5 text-sm gap-2 rounded-pill',
  lg: 'px-8 py-3.5 text-base gap-2.5 rounded-pill',
};

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  leftIcon,
  rightIcon,
  children,
  disabled,
  className = '',
  ...props
}: ButtonProps) {
  const isDisabled = disabled || loading;

  return (
    <button
      className={`inline-flex items-center justify-center font-semibold transition-colors duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      disabled={isDisabled}
      {...props}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin shrink-0" />
      ) : leftIcon ? (
        <span className="shrink-0">{leftIcon}</span>
      ) : null}
      {children}
      {!loading && rightIcon && <span className="shrink-0">{rightIcon}</span>}
    </button>
  );
}
