import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

const STROKE_DEFAULT = "1.7";
const STROKE_THIN = "1.6";
const STROKE_BOLD = "2";
const STROKE_HEAVY = "2.2";

const withSize = (
  width: number,
  height: number,
  viewBox: string,
  children: React.ReactNode,
) =>
  function Icon(props: IconProps) {
    return (
      <svg
        width={width}
        height={height}
        viewBox={viewBox}
        fill="none"
        {...props}
      >
        {children}
      </svg>
    );
  };

export const IconChat = withSize(
  22,
  22,
  "0 0 24 24",
  <path
    d="M4 12c0-4.4 3.6-8 8-8s8 3.6 8 8-3.6 8-8 8c-1 0-2-.2-2.9-.5L5 20l1-3.5C4.7 15 4 13.6 4 12z"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinejoin="round"
  />,
);

export const IconTask = withSize(
  22,
  22,
  "0 0 24 24",
  <>
    <rect x="4" y="5" width="16" height="15" rx="3" stroke="currentColor" strokeWidth={STROKE_DEFAULT} />
    <path
      d="M8 3v4M16 3v4M8 12l2.5 2.5L15 10"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </>,
);

export const IconGoal = withSize(
  22,
  22,
  "0 0 24 24",
  <>
    <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth={STROKE_DEFAULT} />
    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth={STROKE_DEFAULT} />
    <circle cx="12" cy="12" r="1.4" fill="currentColor" />
  </>,
);

export const IconBook = withSize(
  20,
  20,
  "0 0 24 24",
  <path
    d="M6 4h10a3 3 0 013 3v13l-3-2-3 2-3-2-3 2V5a1 1 0 011-1z"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinejoin="round"
  />,
);

export const IconUser = withSize(
  20,
  20,
  "0 0 24 24",
  <>
    <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth={STROKE_DEFAULT} />
    <path
      d="M4 21c0-4.4 3.6-8 8-8s8 3.6 8 8"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
      strokeLinecap="round"
    />
  </>,
);

export const IconRobot = withSize(
  14,
  14,
  "0 0 24 24",
  <>
    <path
      d="M12 3v3"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
      strokeLinecap="round"
    />
    <circle cx="12" cy="2.5" r="1" fill="currentColor" />
    <rect
      x="4"
      y="7"
      width="16"
      height="13"
      rx="3"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
    />
    <circle cx="9" cy="13" r="1.3" fill="currentColor" />
    <circle cx="15" cy="13" r="1.3" fill="currentColor" />
    <path
      d="M9.5 17h5"
      stroke="currentColor"
      strokeWidth={STROKE_THIN}
      strokeLinecap="round"
    />
  </>,
);

export const IconHome = withSize(
  22,
  22,
  "0 0 24 24",
  <path
    d="M4 10l8-7 8 7v10a2 2 0 01-2 2h-4v-7h-4v7H6a2 2 0 01-2-2V10z"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinejoin="round"
  />,
);

export const IconPlus = withSize(
  20,
  20,
  "0 0 24 24",
  <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth={STROKE_BOLD} strokeLinecap="round" />,
);

export const IconClose = withSize(
  18,
  18,
  "0 0 24 24",
  <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth={STROKE_BOLD} strokeLinecap="round" />,
);

export const IconClock = withSize(
  14,
  14,
  "0 0 24 24",
  <>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth={STROKE_DEFAULT} />
    <path d="M12 7v5l3 2" stroke="currentColor" strokeWidth={STROKE_DEFAULT} strokeLinecap="round" />
  </>,
);

export const IconRepeat = withSize(
  14,
  14,
  "0 0 24 24",
  <path
    d="M17 2l4 4-4 4M3 12v-2a4 4 0 014-4h14M7 22l-4-4 4-4M21 12v2a4 4 0 01-4 4H3"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);

export const IconCheck = withSize(
  14,
  14,
  "0 0 24 24",
  <path
    d="M5 12l5 5 9-11"
    stroke="currentColor"
    strokeWidth={STROKE_HEAVY}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);

export const IconCaret = withSize(
  10,
  10,
  "0 0 24 24",
  <path
    d="M8 4l8 8-8 8"
    stroke="currentColor"
    strokeWidth={STROKE_BOLD}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);

export const IconSpark = withSize(
  16,
  16,
  "0 0 24 24",
  <path d="M12 2l2.4 6.6L21 11l-6.6 2.4L12 20l-2.4-6.6L3 11l6.6-2.4L12 2z" fill="currentColor" />,
);

export const IconAgent = withSize(
  22,
  22,
  "0 0 24 24",
  <>
    <path
      d="M12 3v3"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
      strokeLinecap="round"
    />
    <circle cx="12" cy="2.5" r="1" fill="currentColor" />
    <rect
      x="4.5"
      y="7"
      width="15"
      height="13"
      rx="3.5"
      stroke="currentColor"
      strokeWidth={STROKE_DEFAULT}
    />
    <path
      d="M4.5 12H3M21 12h-1.5"
      stroke="currentColor"
      strokeWidth={STROKE_THIN}
      strokeLinecap="round"
    />
    <circle cx="9" cy="13" r="1.35" fill="currentColor" />
    <circle cx="15" cy="13" r="1.35" fill="currentColor" />
    <path
      d="M9.5 17h5"
      stroke="currentColor"
      strokeWidth={STROKE_THIN}
      strokeLinecap="round"
    />
  </>,
);

export const IconSend = withSize(
  20,
  20,
  "0 0 24 24",
  <path
    d="M12 4v16M6 10l6-6 6 6"
    stroke="currentColor"
    strokeWidth={STROKE_BOLD}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);

export const IconPencil = withSize(
  16,
  16,
  "0 0 24 24",
  <path
    d="M4 20h4l10-10-4-4L4 16v4zM14 6l4 4"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);

export const IconFolder = withSize(
  18,
  18,
  "0 0 24 24",
  <path
    d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinejoin="round"
  />,
);

export const IconDoc = withSize(
  16,
  16,
  "0 0 24 24",
  <path
    d="M7 3h7l5 5v11a2 2 0 01-2 2H7a2 2 0 01-2-2V5a2 2 0 012-2zM14 3v5h5"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinejoin="round"
  />,
);

export const IconTrash = withSize(
  18,
  18,
  "0 0 24 24",
  <path
    d="M4 7h16M10 11v6M14 11v6M5 7l1 13a2 2 0 002 2h8a2 2 0 002-2l1-13M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3"
    stroke="currentColor"
    strokeWidth={STROKE_DEFAULT}
    strokeLinecap="round"
    strokeLinejoin="round"
  />,
);
