// A small line-icon set (drawn for PrePro): 24×24 grid, 1.8 stroke, currentColor.
const P: Record<string, string> = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  folder: "M3 6.5A1.5 1.5 0 0 1 4.5 5h4.2l2 2.2h8.8A1.5 1.5 0 0 1 21 8.7V18a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 18z",
  settings: "M12 15.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4zM19.4 13.5a7.6 7.6 0 0 0 0-3l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2.6-1.5L14 2.5h-4l-.4 2.5A7.6 7.6 0 0 0 7 6.5l-2.4-1-2 3.4 2 1.6a7.6 7.6 0 0 0 0 3l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2.6 1.5l.4 2.5h4l.4-2.5a7.6 7.6 0 0 0 2.6-1.5l2.4 1 2-3.4z",
  sparkles: "M12 3l1.7 4.6L18.5 9l-4.8 1.6L12 15l-1.7-4.4L5.5 9l4.8-1.4zM19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8zM5 15l.6 1.4L7 17l-1.4.6L5 19l-.6-1.4L3 17l1.4-.6z",
  sun: "M12 16.5a4.5 4.5 0 1 0 0-9 4.5 4.5 0 0 0 0 9zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M20.5 14.5A8.5 8.5 0 0 1 9.5 3.5a8.5 8.5 0 1 0 11 11z",
  monitor: "M3.5 4.5h17a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1h-17a1 1 0 0 1-1-1v-10a1 1 0 0 1 1-1zM8.5 20.5h7M12 16.5v4",
  check: "M4.5 12.5l5 5 10-11",
  x: "M6 6l12 12M18 6 6 18",
  play: "M7 4.5v15l12.5-7.5z",
  stop: "M6.5 6.5h11v11h-11z",
  download: "M12 3.5v12M7 10.5l5 5 5-5M4.5 20.5h15",
  key: "M14.5 9.5a4.5 4.5 0 1 1-1.3-3.2 4.5 4.5 0 0 1 1.3 3.2zM13.2 12.8 21 20.5M17.5 17l2-2M15.5 15l1.5-1.5",
  link: "M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1",
  refresh: "M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4",
  film: "M3.5 4.5h17v15h-17zM7.5 4.5v15M16.5 4.5v15M3.5 9h4M3.5 15h4M16.5 9h4M16.5 15h4",
  wand: "M4 20 15.5 8.5M14 5l1.5-1.5M18.5 10 20 8.5M17 3v2M21 7h-2M13 7l4 4",
  cpu: "M7.5 7.5h9v9h-9zM9.5 3v4.5M14.5 3v4.5M9.5 16.5V21M14.5 16.5V21M3 9.5h4.5M3 14.5h4.5M16.5 9.5H21M16.5 14.5H21",
  shield: "M12 2.8 19.5 5.8v5.6c0 4.6-3.2 8.5-7.5 9.8-4.3-1.3-7.5-5.2-7.5-9.8V5.8z",
  mic: "M12 14.5a3.5 3.5 0 0 0 3.5-3.5V6a3.5 3.5 0 1 0-7 0v5a3.5 3.5 0 0 0 3.5 3.5zM5.5 11a6.5 6.5 0 0 0 13 0M12 17.5v3.5",
  bell: "M6 17V11a6 6 0 1 1 12 0v6l1.5 2h-15zM10 21a2 2 0 0 0 4 0",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5",
  chevron: "M9 5.5 15.5 12 9 18.5",
  external: "M14 4.5h5.5V10M19.5 4.5 11 13M10 6H5.5A1 1 0 0 0 4.5 7v11.5a1 1 0 0 0 1 1H17a1 1 0 0 0 1-1V14",
  terminal: "M3.5 5.5h17v13h-17zM7 10l3 2.5L7 15M12.5 15h4.5",
  layers: "M12 3.5 21 8.5l-9 5-9-5zM3 13l9 5 9-5",
  scissors: "M6.5 9a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM6.5 20a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5zM8.6 8.1 20 18M8.6 15.9 20 6",
  brief: "M7 3.5h7.5L19 8v12.5H7zM14.5 3.5V8H19M10 12h6M10 15.5h6",
  compass: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM15.5 8.5 13.6 13.6 8.5 15.5l1.9-5.1z",
  export: "M12 15.5v-12M7 8.5l5-5 5 5M4.5 13v6.5h15V13",
  eye: "M2.5 12s3.5-6.5 9.5-6.5S21.5 12 21.5 12s-3.5 6.5-9.5 6.5S2.5 12 2.5 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  lock: "M6.5 10.5h11v10h-11zM8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3",
};

export default function Icon({ name, size = 18, className = "ico", title }: { name: keyof typeof P | string; size?: number; className?: string; title?: string }) {
  const d = P[name] ?? P.info;
  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true} role={title ? "img" : undefined}>
      {title && <title>{title}</title>}
      <path d={d} />
    </svg>
  );
}
