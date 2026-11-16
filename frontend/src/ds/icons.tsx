import type { ReactElement, SVGProps } from 'react';

export type IconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number; title?: string };

function make(paths: ReactElement, opts: { flipRtl?: boolean } = {}) {
  return function Icon({ size = 16, title, className, ...rest }: IconProps) {
    const cls = ['acr-icon', opts.flipRtl ? 'acr-flip-rtl' : '', className ?? ''].filter(Boolean).join(' ');
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.7}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cls}
        role={title ? 'img' : undefined}
        aria-hidden={title ? undefined : true}
        aria-label={title}
        focusable="false"
        {...rest}
      >
        {paths}
      </svg>
    );
  };
}

export const IconSearch = make(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>);
export const IconDeal = make(<><rect x="3" y="7" width="18" height="13" rx="1.5" /><path d="M9 7V5a1.5 1.5 0 0 1 1.5-1.5h3A1.5 1.5 0 0 1 15 5v2M3 13h18" /></>);
export const IconDoc = make(<><path d="M6 3h8l4 4v14H6z" /><path d="M14 3v4h4M9 12h6M9 16h6" /></>);
export const IconGrid = make(<><rect x="3.5" y="3.5" width="17" height="17" rx="1.5" /><path d="M3.5 9.5h17M3.5 15h17M9.5 3.5v17M15 3.5v17" /></>);
export const IconModel = make(<><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /><path d="m4 10 6-6 6 9" /></>);
export const IconDeck = make(<><rect x="3" y="4" width="18" height="12" rx="1.5" /><path d="M12 16v4M8 20h8M7 12l3-3 2.5 2.5L17 8" /></>);
export const IconAgent = make(<><rect x="5" y="8" width="14" height="11" rx="2.5" /><path d="M12 8V4.5M9.5 13.5h.01M14.5 13.5h.01M9.5 16.5h5" /><circle cx="12" cy="3.7" r="1" /></>);
export const IconBell = make(<><path d="M6 17h12l-1.5-2.5V10a4.5 4.5 0 0 0-9 0v4.5z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>);
export const IconSettings = make(<><circle cx="12" cy="12" r="3" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" /></>);
export const IconUser = make(<><circle cx="12" cy="8" r="3.5" /><path d="M5 20c.8-3.6 3.6-5.5 7-5.5s6.2 1.9 7 5.5" /></>);
export const IconPlus = make(<path d="M12 5v14M5 12h14" />);
export const IconUpload = make(<><path d="M12 16V4M7 9l5-5 5 5" /><path d="M4 16v3.5h16V16" /></>);
export const IconDownload = make(<><path d="M12 4v12M7 11l5 5 5-5" /><path d="M4 16v3.5h16V16" /></>);
export const IconCheck = make(<path d="m5 12.5 4.5 4.5L19 7.5" />);
export const IconX = make(<path d="M6 6l12 12M18 6 6 18" />);
export const IconAlert = make(<><path d="M12 3.5 2.5 20h19z" /><path d="M12 10v4.5M12 17.5h.01" /></>);
export const IconInfo = make(<><circle cx="12" cy="12" r="9" /><path d="M12 11v5.5M12 7.5h.01" /></>);
export const IconClock = make(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3.5 2" /></>);
export const IconDollar = make(<><circle cx="12" cy="12" r="9" /><path d="M14.5 9.2c-.4-1-1.4-1.6-2.5-1.6-1.5 0-2.6.8-2.6 2s1 1.7 2.6 2 2.6.8 2.6 2-1.1 2-2.6 2c-1.2 0-2.2-.6-2.6-1.7M12 6v1.6M12 16.4V18" /></>);
export const IconLink = make(<><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></>);
export const IconExternal = make(<><path d="M14 4h6v6M20 4l-9 9" /><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>, { flipRtl: true });
export const IconChevronDown = make(<path d="m6 9 6 6 6-6" />);
export const IconChevronUp = make(<path d="m6 15 6-6 6 6" />);
export const IconChevronRight = make(<path d="m9 6 6 6-6 6" />, { flipRtl: true });
export const IconChevronLeft = make(<path d="m15 6-6 6 6 6" />, { flipRtl: true });
export const IconUndo = make(<><path d="M9 14 4 9l5-5" /><path d="M4 9h10a6 6 0 0 1 0 12h-3" /></>, { flipRtl: true });
export const IconHistory = make(<><path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5" /><path d="M3.5 4v4.5H8M12 8v4.5l3 1.5" /></>);
export const IconDiff = make(<><path d="M7 4v9M2.5 8.5h9" /><path d="M14.5 17h7" /><path d="M14.5 6.5h7M14.5 10.5h4" /></>);
export const IconComment = make(<path d="M4 5.5h16v10.5H9.5L5 20v-4H4z" />, { flipRtl: true });
export const IconPlay = make(<path d="M7 4.5v15l12-7.5z" />, { flipRtl: true });
export const IconPause = make(<path d="M8 5v14M16 5v14" />);
export const IconLock = make(<><rect x="5" y="11" width="14" height="9.5" rx="1.5" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>);
export const IconMail = make(<><rect x="3" y="5.5" width="18" height="13" rx="1.5" /><path d="m3.5 7 8.5 6.5L20.5 7" /></>);
export const IconGlobe = make(<><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.6 2.6 3.6 5.6 3.6 9s-1 6.4-3.6 9c-2.6-2.6-3.6-5.6-3.6-9s1-6.4 3.6-9z" /></>);
export const IconKeyboard = make(<><rect x="2.5" y="6" width="19" height="12" rx="1.5" /><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10" /></>);
export const IconFilter = make(<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z" />);
export const IconMore = make(<><circle cx="5.5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="18.5" cy="12" r="1" fill="currentColor" /></>);
export const IconSun = make(<><circle cx="12" cy="12" r="4" /><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4" /></>);
export const IconMoon = make(<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />);
export const IconSpinner = make(<path d="M12 3a9 9 0 1 0 9 9" />);
export const IconHome = make(<><path d="M4 11 12 4l8 7" /><path d="M6 10v10h12V10" /></>);
export const IconBuilding = make(<><rect x="5" y="3.5" width="14" height="17" rx="1" /><path d="M9 8h.01M13 8h.01M9 12h.01M13 12h.01M10 20.5v-4h4v4" /></>);
export const IconCollapse = make(<path d="M4 6h16M4 12h10M4 18h16" />);

export const ICONS = {
  search: IconSearch,
  deal: IconDeal,
  doc: IconDoc,
  grid: IconGrid,
  model: IconModel,
  deck: IconDeck,
  agent: IconAgent,
  bell: IconBell,
  settings: IconSettings,
  user: IconUser,
  plus: IconPlus,
  upload: IconUpload,
  download: IconDownload,
  check: IconCheck,
  x: IconX,
  alert: IconAlert,
  info: IconInfo,
  clock: IconClock,
  dollar: IconDollar,
  link: IconLink,
  external: IconExternal,
  chevronDown: IconChevronDown,
  chevronUp: IconChevronUp,
  chevronRight: IconChevronRight,
  chevronLeft: IconChevronLeft,
  undo: IconUndo,
  history: IconHistory,
  diff: IconDiff,
  comment: IconComment,
  play: IconPlay,
  pause: IconPause,
  lock: IconLock,
  mail: IconMail,
  globe: IconGlobe,
  keyboard: IconKeyboard,
  filter: IconFilter,
  more: IconMore,
  sun: IconSun,
  moon: IconMoon,
  spinner: IconSpinner,
  home: IconHome,
  building: IconBuilding,
} as const;

export type IconName = keyof typeof ICONS;
