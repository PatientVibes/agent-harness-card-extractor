# agent-app-card-extractor — Plan 2 of 4: Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Vite/React/TypeScript frontend to `agent-app-card-extractor` with a file-drop pane and a dual JSON/XML previewer. The frontend runs against the Plan 1 backend in dev mode via a Vite proxy, and is structured so Plan 4 can bundle it into the installer.

**Architecture:** New `web/` directory at the root of the app repo, a sibling of `app/`. Vite dev server (port 5173) proxies `/uploads`, `/jobs`, `/health` to the backend on `127.0.0.1:8000`. Single-page React app with two panes: `FileDrop.tsx` (drag-drop + file picker, posts to `/uploads`, polls `/jobs/:id`), `Previewer.tsx` (JSON/XML tabs + copy button). Plain CSS, no UI framework. Vitest + Testing Library for component tests.

**Tech Stack:** Node 18+, npm, Vite 5, React 18, TypeScript 5, Vitest 2, @testing-library/react 16, jsdom. No external runtime UI deps beyond React.

**Scope boundary:** No chat WebSocket pane (Plan 3). No installer / static-asset mount in FastAPI (Plan 4). This plan ends when `npm run dev` (in `web/`) + `uv run uvicorn app.main:app` (in repo root) lets you drop a PDF in the browser and see JSON + XML render.

---

## File Structure

```
D:\agent-app-card-extractor\
  web/                          # NEW Vite project root
    package.json
    package-lock.json           # generated
    tsconfig.json
    tsconfig.node.json
    vite.config.ts              # includes server.proxy → backend
    vitest.config.ts            # jsdom + setup file
    index.html                  # entry HTML
    .gitignore                  # node_modules, dist
    src/
      main.tsx                  # React root
      App.tsx                   # composition root: FileDrop + Previewer
      App.css                   # layout + page-level styles
      api.ts                    # typed fetch wrappers (uploadFile, getJob, getJobXml)
      types.ts                  # Job, Extraction, JobStatus
      hooks/
        useJobStatus.ts         # polling hook
      panes/
        FileDrop.tsx
        FileDrop.css
        Previewer.tsx
        Previewer.css
      vite-env.d.ts
      test-setup.ts             # @testing-library/jest-dom matchers
      __tests__/
        App.test.tsx
        api.test.ts
        useJobStatus.test.ts
        FileDrop.test.tsx
        Previewer.test.tsx
  .gitignore                    # MODIFY: add web/node_modules, web/dist
```

Each file has one responsibility. `api.ts` owns HTTP. `useJobStatus.ts` owns polling. `FileDrop.tsx` owns upload UX. `Previewer.tsx` owns the JSON/XML display. `App.tsx` is a thin composition root.

**Prerequisite (one-time):** Node 18+ must be installed on the dev machine. Verify with `node --version` before Task 1. If absent, install from https://nodejs.org/ before starting.

---

### Task 1: Scaffold the Vite + React + TS + Vitest project

**Files:**
- Create: `D:\agent-app-card-extractor\web\package.json`
- Create: `D:\agent-app-card-extractor\web\tsconfig.json`
- Create: `D:\agent-app-card-extractor\web\tsconfig.node.json`
- Create: `D:\agent-app-card-extractor\web\vite.config.ts`
- Create: `D:\agent-app-card-extractor\web\vitest.config.ts`
- Create: `D:\agent-app-card-extractor\web\index.html`
- Create: `D:\agent-app-card-extractor\web\.gitignore`
- Create: `D:\agent-app-card-extractor\web\src\main.tsx`
- Create: `D:\agent-app-card-extractor\web\src\App.tsx` (placeholder)
- Create: `D:\agent-app-card-extractor\web\src\App.css` (empty)
- Create: `D:\agent-app-card-extractor\web\src\vite-env.d.ts`
- Create: `D:\agent-app-card-extractor\web\src\test-setup.ts`
- Create: `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx`
- Modify: `D:\agent-app-card-extractor\.gitignore` (add `web/node_modules/`, `web/dist/`)

- [ ] **Step 1: Verify Node is installed**

Run: `node --version`
Expected: a version starting with `v18.`, `v20.`, or higher.

- [ ] **Step 2: Create the `web/` directory and write `package.json`**

```bash
mkdir D:\agent-app-card-extractor\web
```

`D:\agent-app-card-extractor\web\package.json`:

```json
{
  "name": "agent-app-card-extractor-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.5.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.2",
    "jsdom": "^25.0.1",
    "typescript": "^5.6.2",
    "vite": "^5.4.8",
    "vitest": "^2.1.2"
  }
}
```

- [ ] **Step 3: Write `tsconfig.json`**

`D:\agent-app-card-extractor\web\tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "Bundler",
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Write `tsconfig.node.json`**

`D:\agent-app-card-extractor\web\tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

- [ ] **Step 5: Write `vite.config.ts`**

`D:\agent-app-card-extractor\web\vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/uploads": "http://127.0.0.1:8000",
      "/jobs": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
});
```

- [ ] **Step 6: Write `vitest.config.ts`**

`D:\agent-app-card-extractor\web\vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
  },
});
```

- [ ] **Step 7: Write `index.html`**

`D:\agent-app-card-extractor\web\index.html`:

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Card Extractor</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: Write `web/.gitignore`**

`D:\agent-app-card-extractor\web\.gitignore`:

```
node_modules/
dist/
*.tsbuildinfo
```

- [ ] **Step 9: Write `src/main.tsx`**

`D:\agent-app-card-extractor\web\src\main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./App.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
```

- [ ] **Step 10: Write placeholder `src/App.tsx`**

`D:\agent-app-card-extractor\web\src\App.tsx`:

```tsx
export function App() {
  return <h1>Card Extractor</h1>;
}
```

- [ ] **Step 11: Write empty `src/App.css`**

`D:\agent-app-card-extractor\web\src\App.css`: empty file (0 bytes).

- [ ] **Step 12: Write `src/vite-env.d.ts`**

`D:\agent-app-card-extractor\web\src\vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

- [ ] **Step 13: Write `src/test-setup.ts`**

`D:\agent-app-card-extractor\web\src\test-setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 14: Write the failing smoke test**

`D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { App } from "../App";

describe("App", () => {
  it("renders the app title", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /card extractor/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 15: Install deps + run the smoke test**

From `D:\agent-app-card-extractor\web\`:

```bash
npm install
npm test
```

Expected: `1 passed`.

- [ ] **Step 16: Modify the app repo's root `.gitignore`**

Add these lines to the END of `D:\agent-app-card-extractor\.gitignore`:

```
web/node_modules/
web/dist/
web/*.tsbuildinfo
```

- [ ] **Step 17: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/ .gitignore
git commit -m "feat(web): scaffold Vite + React + TS + Vitest project"
```

(Note: `web/node_modules/` should NOT appear in `git status` because the .gitignore line excludes it. Confirm before committing.)

---

### Task 2: Typed fetch wrappers in `src/api.ts`

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\types.ts`
- Create: `D:\agent-app-card-extractor\web\src\api.ts`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\api.test.ts`

The fetch wrappers use the same paths the Vite dev server proxies. In dev they target `localhost:5173/...` → forwarded to backend. In prod (Plan 4) they target same-origin `/...` directly.

- [ ] **Step 1: Write `src/types.ts`**

```ts
export type JobStatus = "pending" | "running" | "complete" | "failed";

export interface InsuranceData {
  subscriber_name: string;
  member_id: string;
  group_number: string;
  rx_group_number: string;
  plan_type: string;
}

export interface GovernmentData {
  name: string;
  id_number: string;
  expiration_date: string;
}

export interface Extraction {
  card_type: "INSURANCE" | "GOVERNMENT";
  insurance: Partial<InsuranceData>;
  government: Partial<GovernmentData>;
  confidence: number;
  issuer_hint: string;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  source_filename: string;
  created_at: string;
  extractions?: Extraction[];
  error?: string;
}
```

- [ ] **Step 2: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\api.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadFile, getJob, getJobXml } from "../api";

describe("api.uploadFile", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("posts the file as multipart/form-data to /uploads", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 201,
      json: async () => ({ job_id: "abc", status: "pending" }),
    });

    const file = new File([new Uint8Array([1, 2, 3])], "card.pdf", { type: "application/pdf" });
    const result = await uploadFile(file);

    expect(result).toEqual({ job_id: "abc", status: "pending" });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/uploads");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("throws on non-201 response", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 413,
      text: async () => "File too big",
    });
    const file = new File(["x"], "card.pdf", { type: "application/pdf" });
    await expect(uploadFile(file)).rejects.toThrow(/413/);
  });
});

describe("api.getJob", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches /jobs/:id and returns the parsed body", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ job_id: "abc", status: "complete", source_filename: "x.pdf", created_at: "now", extractions: [] }),
    });
    const job = await getJob("abc");
    expect(job.status).toBe("complete");
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/jobs/abc");
  });

  it("throws on 404", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 404,
      text: async () => "Job missing not found",
    });
    await expect(getJob("missing")).rejects.toThrow(/404/);
  });
});

describe("api.getJobXml", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("fetches /jobs/:id/xml as text", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: async () => "<job id=\"abc\"></job>",
    });
    const xml = await getJobXml("abc");
    expect(xml).toBe('<job id="abc"></job>');
    expect((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/jobs/abc/xml");
  });
});
```

- [ ] **Step 3: Run the test, confirm failure**

```bash
cd D:\agent-app-card-extractor\web
npm test
```

Expected: tests fail with `Failed to resolve import "../api"`.

- [ ] **Step 4: Write `src/api.ts`**

```ts
import type { Job } from "./types";

async function expectStatus(r: Response, expected: number): Promise<void> {
  if (r.status !== expected) {
    const body = await r.text().catch(() => "");
    throw new Error(`${r.status} ${r.statusText}: ${body}`);
  }
}

export async function uploadFile(file: File): Promise<{ job_id: string; status: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/uploads", { method: "POST", body: fd });
  await expectStatus(r, 201);
  return r.json();
}

export async function getJob(jobId: string): Promise<Job> {
  const r = await fetch(`/jobs/${encodeURIComponent(jobId)}`);
  await expectStatus(r, 200);
  return r.json();
}

export async function getJobXml(jobId: string): Promise<string> {
  const r = await fetch(`/jobs/${encodeURIComponent(jobId)}/xml`);
  await expectStatus(r, 200);
  return r.text();
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
npm test
```

Expected: 6 passed (1 App + 5 api).

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/types.ts web/src/api.ts web/src/__tests__/api.test.ts
git commit -m "feat(web): typed fetch wrappers for /uploads, /jobs, /jobs/:id/xml"
```

---

### Task 3: `useJobStatus` polling hook

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\hooks\useJobStatus.ts`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\useJobStatus.test.ts`

The hook polls `getJob(jobId)` every 500ms while status is `pending` or `running`, and stops on `complete` or `failed`. Returns `{ job, error }`.

- [ ] **Step 1: Write the failing test**

`D:\agent-app-card-extractor\web\src\__tests__\useJobStatus.test.ts`:

```ts
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useJobStatus } from "../hooks/useJobStatus";
import * as api from "../api";
import type { Job } from "../types";

function makeJob(status: Job["status"], extra: Partial<Job> = {}): Job {
  return {
    job_id: "abc",
    status,
    source_filename: "card.pdf",
    created_at: "2026-05-17T00:00:00Z",
    ...extra,
  };
}

describe("useJobStatus", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("returns null job for null id without polling", () => {
    const spy = vi.spyOn(api, "getJob");
    const { result } = renderHook(() => useJobStatus(null));
    expect(result.current.job).toBeNull();
    expect(spy).not.toHaveBeenCalled();
  });

  it("polls until status is complete", async () => {
    const spy = vi.spyOn(api, "getJob");
    spy.mockResolvedValueOnce(makeJob("running"));
    spy.mockResolvedValueOnce(makeJob("complete", { extractions: [] }));

    const { result } = renderHook(() => useJobStatus("abc"));

    await waitFor(() => expect(result.current.job?.status).toBe("running"));
    await vi.advanceTimersByTimeAsync(500);
    await waitFor(() => expect(result.current.job?.status).toBe("complete"));

    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("stops polling on failed", async () => {
    const spy = vi.spyOn(api, "getJob");
    spy.mockResolvedValueOnce(makeJob("failed", { error: "boom" }));

    const { result } = renderHook(() => useJobStatus("abc"));
    await waitFor(() => expect(result.current.job?.status).toBe("failed"));

    // Advance well past one polling interval — should not call again.
    await vi.advanceTimersByTimeAsync(2000);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("captures fetch errors in `error`", async () => {
    const spy = vi.spyOn(api, "getJob");
    spy.mockRejectedValueOnce(new Error("network down"));

    const { result } = renderHook(() => useJobStatus("abc"));
    await waitFor(() => expect(result.current.error?.message).toMatch(/network down/));
  });
});
```

- [ ] **Step 2: Run the test, confirm failure**

```bash
npm test
```

Expected: fails with `Failed to resolve import "../hooks/useJobStatus"`.

- [ ] **Step 3: Write the hook**

`D:\agent-app-card-extractor\web\src\hooks\useJobStatus.ts`:

```ts
import { useEffect, useState } from "react";
import { getJob } from "../api";
import type { Job } from "../types";

const POLL_INTERVAL_MS = 500;

export function useJobStatus(jobId: string | null): { job: Job | null; error: Error | null } {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (jobId === null) {
      setJob(null);
      setError(null);
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    async function tick(): Promise<void> {
      try {
        const fresh = await getJob(jobId!);
        if (cancelled) return;
        setJob(fresh);
        if (fresh.status === "pending" || fresh.status === "running") {
          timeoutId = setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e : new Error(String(e)));
      }
    }

    tick();

    return () => {
      cancelled = true;
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [jobId]);

  return { job, error };
}
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
npm test
```

Expected: 10 passed (App + api + useJobStatus).

- [ ] **Step 5: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/hooks/useJobStatus.ts web/src/__tests__/useJobStatus.test.ts
git commit -m "feat(web): useJobStatus hook polls until complete/failed"
```

---

### Task 4: `FileDrop` pane

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\panes\FileDrop.tsx`
- Create: `D:\agent-app-card-extractor\web\src\panes\FileDrop.css`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\FileDrop.test.tsx`

Accepts a PDF via drag-and-drop OR file picker. Calls `uploadFile`, raises `onJobCreated(job_id)` to the parent. Shows a status line ("Drop a PDF", "Uploading…", error text). Rejects non-PDF.

- [ ] **Step 1: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\FileDrop.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { FileDrop } from "../panes/FileDrop";
import * as api from "../api";

describe("FileDrop", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the drop prompt by default", () => {
    render(<FileDrop onJobCreated={() => {}} />);
    expect(screen.getByText(/drop a pdf/i)).toBeInTheDocument();
  });

  it("uploads a file selected via the picker and reports job_id", async () => {
    const spy = vi.spyOn(api, "uploadFile").mockResolvedValueOnce({ job_id: "abc", status: "pending" });
    const onJobCreated = vi.fn();

    render(<FileDrop onJobCreated={onJobCreated} />);
    const file = new File([new Uint8Array([1, 2, 3])], "card.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/choose pdf/i) as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(spy).toHaveBeenCalledWith(file);
    expect(onJobCreated).toHaveBeenCalledWith("abc");
  });

  it("rejects non-PDF files without calling upload", async () => {
    const spy = vi.spyOn(api, "uploadFile");
    const onJobCreated = vi.fn();

    render(<FileDrop onJobCreated={onJobCreated} />);
    const file = new File(["png"], "card.png", { type: "image/png" });
    const input = screen.getByLabelText(/choose pdf/i) as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(spy).not.toHaveBeenCalled();
    expect(onJobCreated).not.toHaveBeenCalled();
    expect(screen.getByText(/must be a pdf/i)).toBeInTheDocument();
  });

  it("displays upload errors", async () => {
    vi.spyOn(api, "uploadFile").mockRejectedValueOnce(new Error("413 too big"));
    const onJobCreated = vi.fn();

    render(<FileDrop onJobCreated={onJobCreated} />);
    const file = new File(["x"], "card.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/choose pdf/i) as HTMLInputElement;
    await userEvent.upload(input, file);

    expect(await screen.findByText(/413 too big/)).toBeInTheDocument();
    expect(onJobCreated).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run, confirm failure**

```bash
npm test -- FileDrop
```

Expected: `Failed to resolve import "../panes/FileDrop"`.

- [ ] **Step 3: Write `FileDrop.tsx`**

`D:\agent-app-card-extractor\web\src\panes\FileDrop.tsx`:

```tsx
import { useState } from "react";
import { uploadFile } from "../api";
import "./FileDrop.css";

interface Props {
  onJobCreated: (jobId: string) => void;
}

type UiState =
  | { kind: "idle" }
  | { kind: "uploading"; filename: string }
  | { kind: "error"; message: string };

export function FileDrop({ onJobCreated }: Props) {
  const [state, setState] = useState<UiState>({ kind: "idle" });
  const [isDragging, setIsDragging] = useState(false);

  async function handleFile(file: File): Promise<void> {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setState({ kind: "error", message: "File must be a PDF" });
      return;
    }
    setState({ kind: "uploading", filename: file.name });
    try {
      const r = await uploadFile(file);
      setState({ kind: "idle" });
      onJobCreated(r.job_id);
    } catch (e) {
      setState({ kind: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }

  return (
    <div
      className={`file-drop ${isDragging ? "file-drop--dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragging(true);
      }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setIsDragging(false);
        const f = e.dataTransfer.files[0];
        if (f) void handleFile(f);
      }}
    >
      <label className="file-drop__label">
        <span>Drop a PDF here, or</span>
        <span className="file-drop__button">choose PDF</span>
        <input
          type="file"
          accept="application/pdf"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleFile(f);
          }}
        />
      </label>
      <div className="file-drop__status" role="status">
        {state.kind === "uploading" && `Uploading ${state.filename}…`}
        {state.kind === "error" && state.message}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Write `FileDrop.css`**

`D:\agent-app-card-extractor\web\src\panes\FileDrop.css`:

```css
.file-drop {
  border: 2px dashed #888;
  border-radius: 8px;
  padding: 2rem;
  text-align: center;
  transition: background-color 0.15s, border-color 0.15s;
}
.file-drop--dragging {
  background-color: #eef;
  border-color: #44a;
}
.file-drop__label {
  display: inline-flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: center;
  cursor: pointer;
}
.file-drop__label input[type="file"] {
  display: none;
}
.file-drop__button {
  display: inline-block;
  padding: 0.5rem 1rem;
  background-color: #44a;
  color: white;
  border-radius: 4px;
}
.file-drop__status {
  margin-top: 1rem;
  min-height: 1.5rem;
  color: #555;
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
npm test
```

Expected: 14 passed (10 prior + 4 FileDrop).

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/panes/FileDrop.tsx web/src/panes/FileDrop.css web/src/__tests__/FileDrop.test.tsx
git commit -m "feat(web): FileDrop pane uploads PDF and reports job_id"
```

---

### Task 5: `Previewer` pane (JSON / XML tabs + copy)

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\panes\Previewer.tsx`
- Create: `D:\agent-app-card-extractor\web\src\panes\Previewer.css`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\Previewer.test.tsx`

Takes a `jobId` prop. Internally fetches JSON via `getJob(jobId)` and XML via `getJobXml(jobId)` when the job is complete. Two tabs: JSON (formatted with `JSON.stringify(payload, null, 2)`) and XML (pretty-printed via a small helper). Each tab has a "Copy" button.

- [ ] **Step 1: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\Previewer.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Previewer } from "../panes/Previewer";
import * as api from "../api";
import type { Job } from "../types";

function makeJob(): Job {
  return {
    job_id: "abc",
    status: "complete",
    source_filename: "card.pdf",
    created_at: "2026-05-17T00:00:00Z",
    extractions: [
      {
        card_type: "INSURANCE",
        insurance: { member_id: "M1" },
        government: {},
        confidence: 0.9,
        issuer_hint: "Aetna",
      },
    ],
  };
}

describe("Previewer", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when jobId is null", () => {
    render(<Previewer jobId={null} />);
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("fetches and displays the JSON view by default", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(makeJob());
    vi.spyOn(api, "getJobXml").mockResolvedValue("<job></job>");

    render(<Previewer jobId="abc" />);
    await waitFor(() => expect(screen.getByText(/M1/)).toBeInTheDocument());
    expect(screen.getByRole("tab", { name: /json/i, selected: true })).toBeInTheDocument();
  });

  it("switches to XML tab on click", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(makeJob());
    vi.spyOn(api, "getJobXml").mockResolvedValue('<job id="abc"><extractions/></job>');

    render(<Previewer jobId="abc" />);
    await waitFor(() => expect(screen.getByText(/M1/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("tab", { name: /xml/i }));
    await waitFor(() => expect(screen.getByText(/<job id="abc">/)).toBeInTheDocument());
  });

  it("copies the active payload to clipboard", async () => {
    vi.spyOn(api, "getJob").mockResolvedValue(makeJob());
    vi.spyOn(api, "getJobXml").mockResolvedValue("<job></job>");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    render(<Previewer jobId="abc" />);
    await waitFor(() => expect(screen.getByText(/M1/)).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /copy/i }));

    expect(writeText).toHaveBeenCalled();
    expect(writeText.mock.calls[0][0]).toContain("M1");
  });
});
```

- [ ] **Step 2: Run, confirm failure**

```bash
npm test -- Previewer
```

Expected: import resolution fails.

- [ ] **Step 3: Write `Previewer.tsx`**

`D:\agent-app-card-extractor\web\src\panes\Previewer.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getJob, getJobXml } from "../api";
import type { Job } from "../types";
import "./Previewer.css";

interface Props {
  jobId: string | null;
}

type Tab = "json" | "xml";

function prettyXml(xml: string): string {
  const tokens = xml.replace(/>\s*</g, "><").replace(/></g, ">\n<").split("\n");
  let depth = 0;
  return tokens
    .map((line) => {
      if (line.match(/^<\/\w/)) depth = Math.max(0, depth - 1);
      const indented = "  ".repeat(depth) + line;
      if (line.match(/^<\w[^>]*[^/]>(?!.*<\/)/)) depth += 1;
      return indented;
    })
    .join("\n");
}

export function Previewer({ jobId }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [xml, setXml] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("json");

  useEffect(() => {
    if (jobId === null) {
      setJob(null);
      setXml(null);
      return;
    }
    let cancelled = false;
    Promise.all([getJob(jobId), getJobXml(jobId)])
      .then(([j, x]) => {
        if (cancelled) return;
        setJob(j);
        setXml(x);
      })
      .catch(() => {
        if (cancelled) return;
        setJob(null);
        setXml(null);
      });
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  if (jobId === null) return null;

  const jsonText = job ? JSON.stringify(job, null, 2) : "Loading…";
  const xmlText = xml ? prettyXml(xml) : "Loading…";
  const active = tab === "json" ? jsonText : xmlText;

  return (
    <div className="previewer">
      <div role="tablist" className="previewer__tabs">
        <button
          role="tab"
          aria-selected={tab === "json"}
          onClick={() => setTab("json")}
          className={tab === "json" ? "previewer__tab previewer__tab--active" : "previewer__tab"}
        >
          JSON
        </button>
        <button
          role="tab"
          aria-selected={tab === "xml"}
          onClick={() => setTab("xml")}
          className={tab === "xml" ? "previewer__tab previewer__tab--active" : "previewer__tab"}
        >
          XML
        </button>
        <button
          className="previewer__copy"
          onClick={() => void navigator.clipboard.writeText(active)}
        >
          Copy
        </button>
      </div>
      <pre className="previewer__body">{active}</pre>
    </div>
  );
}
```

- [ ] **Step 4: Write `Previewer.css`**

`D:\agent-app-card-extractor\web\src\panes\Previewer.css`:

```css
.previewer {
  display: flex;
  flex-direction: column;
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
}
.previewer__tabs {
  display: flex;
  background-color: #f3f3f3;
  border-bottom: 1px solid #ddd;
}
.previewer__tab {
  padding: 0.5rem 1rem;
  background: none;
  border: none;
  cursor: pointer;
  color: #555;
}
.previewer__tab--active {
  background-color: white;
  color: #222;
  border-bottom: 2px solid #44a;
}
.previewer__copy {
  margin-left: auto;
  margin-right: 0.5rem;
  align-self: center;
  padding: 0.25rem 0.75rem;
  border: 1px solid #aaa;
  border-radius: 4px;
  background: white;
  cursor: pointer;
}
.previewer__body {
  margin: 0;
  padding: 1rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
  background-color: #fafafa;
  overflow: auto;
  max-height: 70vh;
  white-space: pre;
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
npm test
```

Expected: 18 passed (14 prior + 4 Previewer).

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/panes/Previewer.tsx web/src/panes/Previewer.css web/src/__tests__/Previewer.test.tsx
git commit -m "feat(web): Previewer pane with JSON/XML tabs and copy button"
```

---

### Task 6: Compose the App with status display

**Files:**
- Modify: `D:\agent-app-card-extractor\web\src\App.tsx` (replace placeholder)
- Modify: `D:\agent-app-card-extractor\web\src\App.css` (page styles)
- Modify: `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx` (new integration assertions)

The composed App holds `jobId` state. `FileDrop` calls `setJobId`. A status banner shows the current job's status (via `useJobStatus`) — only when the job exists. `Previewer` mounts when status is `complete`.

- [ ] **Step 1: Update `App.test.tsx`**

Replace the contents of `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { App } from "../App";
import * as api from "../api";

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the file-drop pane on first load", () => {
    render(<App />);
    expect(screen.getByText(/drop a pdf/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("shows status and previewer after upload completes", async () => {
    vi.spyOn(api, "uploadFile").mockResolvedValue({ job_id: "abc", status: "pending" });
    vi.spyOn(api, "getJob").mockResolvedValue({
      job_id: "abc",
      status: "complete",
      source_filename: "card.pdf",
      created_at: "now",
      extractions: [
        {
          card_type: "INSURANCE",
          insurance: { member_id: "M1" },
          government: {},
          confidence: 0.9,
          issuer_hint: "Aetna",
        },
      ],
    });
    vi.spyOn(api, "getJobXml").mockResolvedValue('<job id="abc"></job>');

    render(<App />);
    const file = new File(["x"], "card.pdf", { type: "application/pdf" });
    const input = screen.getByLabelText(/choose pdf/i) as HTMLInputElement;
    await userEvent.upload(input, file);

    await waitFor(() => expect(screen.getByText(/M1/)).toBeInTheDocument());
    expect(screen.getByText(/status:\s*complete/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test, confirm failure**

```bash
npm test -- App
```

Expected: the second test fails because the current App is still the placeholder heading.

- [ ] **Step 3: Replace `App.tsx`**

`D:\agent-app-card-extractor\web\src\App.tsx`:

```tsx
import { useState } from "react";
import { FileDrop } from "./panes/FileDrop";
import { Previewer } from "./panes/Previewer";
import { useJobStatus } from "./hooks/useJobStatus";

export function App() {
  const [jobId, setJobId] = useState<string | null>(null);
  const { job, error } = useJobStatus(jobId);

  return (
    <div className="app">
      <header className="app__header">
        <h1>Card Extractor</h1>
      </header>
      <main className="app__main">
        <section className="app__pane app__pane--left">
          <FileDrop onJobCreated={setJobId} />
          {job && (
            <div className="app__status" role="status">
              <strong>{job.source_filename}</strong>
              <span className={`app__status-pill app__status-pill--${job.status}`}>
                status: {job.status}
              </span>
              {job.status === "failed" && job.error && (
                <p className="app__status-error">{job.error}</p>
              )}
            </div>
          )}
          {error && <p className="app__status-error">{error.message}</p>}
        </section>
        <section className="app__pane app__pane--right">
          <Previewer jobId={job?.status === "complete" ? jobId : null} />
        </section>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Replace `App.css`**

`D:\agent-app-card-extractor\web\src\App.css`:

```css
* {
  box-sizing: border-box;
}
html, body, #root {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background-color: #fafbfc;
}
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.app__header {
  padding: 1rem 2rem;
  border-bottom: 1px solid #eee;
  background-color: white;
}
.app__header h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}
.app__main {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 1.5rem;
  padding: 1.5rem 2rem;
  overflow: hidden;
}
.app__pane {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: auto;
}
.app__status {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background-color: white;
  border: 1px solid #eee;
  border-radius: 6px;
}
.app__status-pill {
  align-self: flex-start;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
}
.app__status-pill--pending,
.app__status-pill--running {
  background-color: #fff4cc;
  color: #7a5b00;
}
.app__status-pill--complete {
  background-color: #d6f5d6;
  color: #185c18;
}
.app__status-pill--failed {
  background-color: #fadcdc;
  color: #842525;
}
.app__status-error {
  margin: 0;
  color: #842525;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
npm test
```

Expected: 19 passed (App's 2 tests + 5 api + 4 useJobStatus + 4 FileDrop + 4 Previewer = 19).

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/App.tsx web/src/App.css web/src/__tests__/App.test.tsx
git commit -m "feat(web): App composes FileDrop + status + Previewer"
```

---

### Task 7: README + manual smoke

**Files:**
- Modify: `D:\agent-app-card-extractor\README.md`

Update the project README to document the new dev workflow: two terminals, backend on 8000, frontend on 5173, browser at `http://localhost:5173`.

- [ ] **Step 1: Replace `README.md`**

`D:\agent-app-card-extractor\README.md`:

````markdown
# agent-app-card-extractor

Installable card-extraction app. Wraps [agent-harness-card-extractor](../agent-harness-card-extractor) as a library.

## Status

- Plan 1 (backend): **complete** — `POST /uploads`, `GET /jobs/:id`, `GET /jobs/:id/xml`.
- Plan 2 (frontend): **complete** — file-drop pane + dual JSON/XML previewer.
- Plan 3 (chat agent): next.
- Plan 4 (installer): pending.

## Dev — two terminals

**Terminal 1: backend**

```bash
uv sync --extra dev
cp .env.example .env  # fill in AI_GATEWAY_KEY
uv run uvicorn app.main:app --reload
```

Backend listens on `http://127.0.0.1:8000`.

**Terminal 2: frontend**

```bash
cd web
npm install  # first time only
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/uploads`, `/jobs`, `/health` to the backend.

## Tests

```bash
uv run pytest -v             # backend
cd web && npm test           # frontend
```
````

- [ ] **Step 2: Manual sanity check**

This step is optional and requires a real `AI_GATEWAY_KEY`. If you have one, follow the README dev steps, drop a PDF in the browser, and confirm:
- Status pill transitions to `complete`.
- JSON tab shows the extraction data.
- XML tab shows the same data formatted as XML.
- Copy button writes to the clipboard.

If you don't have a key, skip this step — the tests already exercise the full UI surface against mocked APIs.

- [ ] **Step 3: Commit**

```bash
cd D:\agent-app-card-extractor
git add README.md
git commit -m "docs: README dev workflow for Plan 2 (frontend)"
```

---

## Plan 2 exit criteria

- [ ] `cd web && npm test` reports 19 tests passing.
- [ ] `cd web && npm run build` succeeds (TypeScript compiles, Vite builds to `web/dist/`).
- [ ] `cd web && npm run dev` starts the dev server cleanly.
- [ ] With the backend running on `:8000`, visiting `http://localhost:5173` shows the file-drop pane.
- [ ] Dropping (or selecting) a PDF transitions the status pill from pending → running → complete.
- [ ] Once complete, the previewer shows JSON by default and switches to XML on tab click.
- [ ] The copy button writes the active tab's content to the clipboard.
- [ ] No frontend code under `app/` — `app/` is Python-only and unchanged in Plan 2.

When all boxes are checked, Plan 2 is done. Plan 3 (chat WebSocket + edit-proposal agent) is next.
