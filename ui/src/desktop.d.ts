// Present only inside the PrePro desktop app (Electron preload); the browser build works without it.
export interface UpdateState {
  current: string;
  mode: "auto" | "notify" | "off";
  status: "idle" | "checking" | "latest" | "available" | "downloading" | "ready" | "error";
  latest: string | null;
  notes: string;
  page: string;
  progress: number;
  error: string | null;
  checkedAt: string | null;
  canInstall: boolean;
  busy: boolean;
}

declare global {
  interface Window {
    prepro?: {
      isDesktop: boolean;
      pickFolder: () => Promise<string | null>;
      reveal: (path: string) => Promise<void>;
      updates?: {
        get: () => Promise<UpdateState>;
        check: () => Promise<UpdateState>;
        setMode: (mode: UpdateState["mode"]) => Promise<UpdateState>;
        download: () => Promise<UpdateState>;
        install: () => Promise<void>;
        openPage: () => Promise<void>;
        onChange: (cb: (s: UpdateState) => void) => () => void;
      };
    };
  }
}
