// Present only inside the PrePro desktop app (Electron preload); the browser build works without it.
interface Window {
  prepro?: {
    isDesktop: boolean;
    pickFolder: () => Promise<string | null>;
    reveal: (path: string) => Promise<void>;
  };
}
