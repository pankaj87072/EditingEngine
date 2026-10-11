export function Logo({ className = '' }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2.5 font-display text-lg font-bold tracking-tight ${className}`}>
      <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
        <defs>
          <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#8b6bff" />
            <stop offset="1" stopColor="#4c8dff" />
          </linearGradient>
        </defs>
        <rect x="8" y="3.5" width="16" height="25" rx="4" fill="none" stroke="url(#lg)" strokeWidth="2.4" />
        <path d="M14 11.5v9l7-4.5z" fill="url(#lg)" />
      </svg>
      AutoVideoGen
    </span>
  );
}
