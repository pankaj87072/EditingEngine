import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/cn';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const base =
  'inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-colors select-none ' +
  'disabled:cursor-not-allowed disabled:opacity-50 whitespace-nowrap';
const variants: Record<Variant, string> = {
  primary: 'brand-gradient text-white shadow-[0_8px_24px_-8px_rgb(var(--violet)/.7)] hover:brightness-110 active:brightness-95',
  secondary: 'border border-line bg-raised text-ink hover:border-mute/60 hover:bg-raised/70',
  ghost: 'text-mute hover:bg-raised hover:text-ink',
  danger: 'border border-bad/40 bg-bad/10 text-bad hover:bg-bad/20',
};
const sizes: Record<Size, string> = {
  sm: 'h-9 px-3 text-sm',
  md: 'h-11 px-4 text-sm',
  lg: 'h-12 px-6 text-base',
};

export const buttonClasses = (variant: Variant = 'primary', size: Size = 'md', extra?: string) =>
  cn(base, variants[variant], sizes[size], extra);

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'primary', size = 'md', className, type = 'button', ...rest },
  ref,
) {
  return <button ref={ref} type={type} className={buttonClasses(variant, size, className)} {...rest} />;
});
