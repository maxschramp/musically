// ============================================
// Musically — Button Component
// Cohere-styled button with variants and sizes
// ============================================

import { type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'accent' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
}

const variantClasses: Record<string, string> = {
  primary:
    'bg-primary text-on-primary hover:bg-[#2a2a30] active:bg-[#0d0d10] focus-visible:ring-2 focus-visible:ring-focus-blue focus-visible:ring-offset-2',
  accent:
    'bg-coral text-white hover:bg-[#e56a4e] active:bg-[#cc5f46] focus-visible:ring-2 focus-visible:ring-coral focus-visible:ring-offset-2',
  ghost:
    'bg-transparent text-ink hover:bg-gray-100 active:bg-gray-200 focus-visible:ring-2 focus-visible:ring-focus-blue focus-visible:ring-offset-2',
  danger:
    'bg-red-600 text-white hover:bg-red-700 active:bg-red-800 focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2',
};

const sizeClasses: Record<string, string> = {
  sm: 'px-3 py-1.5 text-sm gap-1.5 rounded-sm',
  md: 'px-4 py-2 text-sm gap-2 rounded-pill',
  lg: 'px-6 py-3 text-lg gap-2.5 rounded-pill',
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
      className={`inline-flex items-center justify-center font-medium transition-colors duration-150 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
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
