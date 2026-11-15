import type { ReactNode, SVGProps } from "react";

/** Dependency-free, consistent 24px outline iconography for the workstation. */
export type IconName =
  | "audio" | "mic" | "music" | "upload" | "trash" | "arrow-down" | "expand" | "info" | "sparkles" | "chat" | "image" | "code" | "models" | "overview" | "settings"
  | "arrow-right" | "arrow-up" | "plus" | "cpu" | "hard-drive" | "shield"
  | "bolt" | "layers" | "activity" | "chevron-down" | "chevron-right" | "folder" | "send"
  | "menu" | "x" | "panel-left-close" | "panel-left-open" | "search" | "file";

export function Icon({ name, size = 20, ...props }: SVGProps<SVGSVGElement> & { name: IconName; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.75, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true as const };
  const paths: Record<IconName, ReactNode> = {
    audio: <><path d="M4 10v4m4-7v10m4-13v16m4-13v10m4-7v4"/></>,
    mic: <><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2m-7 9v3m-4 0h8"/></>,
    music: <><path d="M9 18V5l12-2v13M9 8l12-2"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="18" cy="16" rx="3" ry="2"/></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 16v4h16v-4"/></>,
    trash: <><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/></>,
    "arrow-down": <><path d="M12 4v16m-6-6 6 6 6-6"/></>,
    expand: <><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/></>,
    info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/></>,
    sparkles: <><path d="m12 3 1.75 5.25L19 10l-5.25 1.75L12 17l-1.75-5.25L5 10l5.25-1.75L12 3Z" /><path d="m19 17 .85 2.15L22 20l-2.15.85L19 23l-.85-2.15L16 20l2.15-.85L19 17ZM4 2l.6 1.4L6 4l-1.4.6L4 6l-.6-1.4L2 4l1.4-.6L4 2Z" /></>,
    chat: <><path d="M20 11.5a7.7 7.7 0 0 1-8 7.5 9.8 9.8 0 0 1-3-.5L4 20l1.3-4A7.6 7.6 0 0 1 4 11.5 7.7 7.7 0 0 1 12 4a7.7 7.7 0 0 1 8 7.5Z" /><path d="M8.5 11.5h7" /></>,
    image: <><rect x="3" y="3" width="18" height="18" rx="3" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="m4 17 5.5-5 3.5 3 3-3 4 4" /></>,
    code: <><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" /></>,
    models: <><rect x="4" y="4" width="16" height="16" rx="4" /><rect x="9" y="9" width="6" height="6" rx="1" /><path d="M9 1v3m6-3v3M9 20v3m6-3v3M20 9h3m-3 6h3M1 9h3m-3 6h3" /></>,
    overview: <><rect x="3" y="3" width="8" height="8" rx="2" /><rect x="13" y="3" width="8" height="5" rx="2" /><rect x="13" y="10" width="8" height="11" rx="2" /><rect x="3" y="13" width="8" height="8" rx="2" /></>,
    settings: <><path d="M12 3a2 2 0 0 1 2 2l.1 1.1 1.4.8 1-.5a2 2 0 0 1 2.7.7l1 1.7a2 2 0 0 1-.7 2.7l-.9.6v1.7l.9.6a2 2 0 0 1 .7 2.7l-1 1.7a2 2 0 0 1-2.7.7l-1-.5-1.4.8L14 21a2 2 0 0 1-2 2 2 2 0 0 1-2-2l-.1-1.1-1.4-.8-1 .5a2 2 0 0 1-2.7-.7l-1-1.7a2 2 0 0 1 .7-2.7l.9-.6v-1.7l-.9-.6a2 2 0 0 1-.7-2.7l1-1.7a2 2 0 0 1 2.7-.7l1 .5 1.4-.8L10 5a2 2 0 0 1 2-2Z" transform="translate(0 -1) scale(1 .93)" /><circle cx="12" cy="12" r="3" /></>,
    "arrow-right": <><path d="M4 12h16m-7-7 7 7-7 7" /></>,
    "arrow-up": <><path d="M12 19V5m-7 7 7-7 7 7" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    cpu: <><rect x="5" y="5" width="14" height="14" rx="3" /><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3" /><rect x="9" y="9" width="6" height="6" rx="1" /></>,
    "hard-drive": <><rect x="3" y="6" width="18" height="12" rx="3" /><path d="M3 13h18M7 16h.01M11 16h.01" /></>,
    shield: <><path d="M12 2 4 5v6c0 5 3.5 8.6 8 11 4.5-2.4 8-6 8-11V5l-8-3Z" /><path d="m9 12 2 2 4-4" /></>,
    bolt: <><path d="m13 2-9 12h7l-1 8 10-12h-7l0-8Z" /></>,
    layers: <><path d="m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5" /></>,
    activity: <><path d="M3 12h4l3-7 4 14 3-7h4" /></>,
    "chevron-down": <><path d="m6 9 6 6 6-6" /></>,
    "chevron-right": <><path d="m9 6 6 6-6 6" /></>,
    menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
    x: <><path d="M5 5l14 14M19 5 5 19" /></>,
    "panel-left-close": <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m8-11-3 3 3 3" /></>,
    "panel-left-open": <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16m6-11 3 3-3 3" /></>,
    folder: <><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /></>,
    search: <><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 5 5"/></>,
    file: <><path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M14 3v6h5"/></>,
    send: <><path d="m4 19 16-7L4 5l2 7-2 7Zm2-7h14" /></>,
  };
  return <svg {...common} {...props}>{paths[name]}</svg>;
}
