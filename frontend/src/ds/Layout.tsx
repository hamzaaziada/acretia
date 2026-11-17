import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { cx } from './util';

export function Wordmark({ size = 20, label = 'Acretia' }: { size?: number; label?: string }) {
  return (
    <svg className="acr-wordmark" height={size} viewBox="0 0 108 24" role="img" aria-label={label}>
      <path d="M2 21 10.5 3 19 21h-3.7l-4.8-10.9L7.2 21z" fill="var(--acr-chrome-accent)" />
      <path d="M12.5 21 17 11.5 21.5 21z" fill="currentColor" opacity="0.55" />
      <text x="27" y="17.5" fontFamily="Inter, 'IBM Plex Sans Arabic', sans-serif" fontSize="16" fontWeight="600" letterSpacing="-0.3" fill="currentColor">
        Acretia
      </text>
    </svg>
  );
}

export function Sidebar({ brand, children, footer, label }: { brand: ReactNode; children: ReactNode; footer?: ReactNode; label: string }) {
  return (
    <aside className="acr-sidebar" aria-label={label}>
      <div className="acr-sidebar__brand">{brand}</div>
      <div className="acr-sidebar__scroll">{children}</div>
      {footer && <div className="acr-sidebar__foot">{footer}</div>}
    </aside>
  );
}

export function SidebarNav({ label, children }: { label: string; children: ReactNode }) {
  return (
    <nav aria-label={label} className="acr-sidebar__nav">
      {children}
    </nav>
  );
}

export function SidebarLink({ to, icon, children, badge, end }: { to: string; icon: ReactNode; children: ReactNode; badge?: number; end?: boolean }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => cx('acr-navlink', isActive && 'is-active')}>
      <span className="acr-navlink__icon">{icon}</span>
      <span className="acr-navlink__label">{children}</span>
      {badge != null && badge > 0 && <span className="acr-navlink__badge acr-num">{badge > 99 ? '99+' : badge}</span>}
    </NavLink>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="acr-section-label">{children}</div>;
}

export function PageHeader({ title, subtitle, actions, meta, breadcrumb }: { title: string; subtitle?: ReactNode; actions?: ReactNode; meta?: ReactNode; breadcrumb?: ReactNode }) {
  return (
    <header className="acr-pageheader">
      <div className="acr-pageheader__main">
        {breadcrumb && <div className="acr-pageheader__crumb">{breadcrumb}</div>}
        <h1 className="acr-pageheader__title" dir="auto">{title}</h1>
        {subtitle && <div className="acr-pageheader__sub">{subtitle}</div>}
        {meta && <div className="acr-pageheader__meta">{meta}</div>}
      </div>
      {actions && <div className="acr-pageheader__actions">{actions}</div>}
    </header>
  );
}

export function Panel({ title, actions, children, flush, className }: { title?: string; actions?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={cx('acr-panel', className)}>
      {(title || actions) && (
        <div className="acr-panel__head">
          {title && <h2 className="acr-panel__title" dir="auto">{title}</h2>}
          {actions && <div className="acr-panel__actions">{actions}</div>}
        </div>
      )}
      <div className={cx('acr-panel__body', flush && 'is-flush')}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="acr-stat">
      <div className="acr-stat__label">{label}</div>
      <div className="acr-stat__value acr-num">{value}</div>
      {hint && <div className="acr-stat__hint">{hint}</div>}
    </div>
  );
}
