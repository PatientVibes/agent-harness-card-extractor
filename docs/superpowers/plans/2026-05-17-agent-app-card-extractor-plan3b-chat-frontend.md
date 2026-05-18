# agent-app-card-extractor — Plan 3b of 4: Chat Frontend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive chat pane to the Plan 2 frontend that talks to the Plan 3a WebSocket backend. The user can chat with the agent about a completed extraction; the agent proposes field edits via inline accept/reject cards; accepted edits refresh the previewer.

**Architecture:** New `useChat` hook owns one `WebSocket` per `jobId` and exposes a flat `items: ChatItem[]` timeline plus action handlers. New `Chat.tsx` renders the timeline + input box, and `EditProposal.tsx` renders the per-proposal diff card with accept/reject. `App.tsx` mounts `Chat` in the right column under `Previewer` once the job is `complete`. After an accepted proposal, the previewer is bumped (force-refresh) so the user sees the mutated JSON. Vite dev proxy is extended with `ws: true` so the WS upgrade reaches the FastAPI backend.

**Tech Stack:** React 18, TypeScript 5, Vite 5, Vitest 2, @testing-library/react 16. No new runtime dependencies. WebSocket is the platform global.

**Scope boundary:** No installer / static-asset wiring (Plan 4). No new backend changes (Plan 3a is the contract). No re-examine VLM tool UI (the backend doesn't expose it yet — Plan 3a deferred it). This plan ends when `npm test` reports 48 passing frontend tests (19 from Plan 2 + 29 new) AND a manual smoke against the live backend shows a chat round-trip with one accepted proposal.

---

## File Structure

```
D:\agent-app-card-extractor\
  web/
    vite.config.ts                          # MODIFY: enable WS proxy for /chat
    src/
      types.ts                              # MODIFY: add ChatItem, Proposal, ChatEvent
      hooks/
        useChat.ts                          # NEW: WebSocket state machine + actions
      panes/
        Chat.tsx                            # NEW: timeline + input box
        Chat.css                            # NEW
        EditProposal.tsx                    # NEW: diff card + accept/reject buttons
        EditProposal.css                    # NEW
      App.tsx                               # MODIFY: mount Chat under Previewer
      App.css                               # MODIFY: right-column row split
      __tests__/
        useChat.test.ts                     # NEW
        EditProposal.test.tsx               # NEW
        Chat.test.tsx                       # NEW
        App.test.tsx                        # MODIFY: chat-present-when-complete assertion
```

Each file has one responsibility. `useChat.ts` owns WebSocket lifecycle + state. `Chat.tsx` owns the timeline render and message-input UX. `EditProposal.tsx` is a pure presentational diff card. `App.tsx` composes.

---

## Type design (shared across tasks)

The WS protocol from Plan 3a defines these events. We model them as a discriminated union and reduce them into a flat timeline:

| Backend event | Frontend timeline item |
|---|---|
| `{type:'ready', job_id}` | (no item — sets connection status) |
| `{type:'history', messages: [{role, content, tool_call_id}]}` | one item per row (mapped by role) |
| `{type:'assistant_message', content}` | `{kind:'assistant', content}` |
| `{type:'tool_call', name, args, result}` | `{kind:'tool', summary: "name(args) → result"}` |
| `{type:'proposal', proposal_id, path, old_value, new_value}` | `{kind:'proposal', proposal, status:'pending'}` |
| `{type:'applied', proposal_id}` | (mutates existing item's `status` to `'applied'`) |
| `{type:'rejected', proposal_id}` | (mutates existing item's `status` to `'rejected'`) |
| `{type:'error', message}` | (sets `error` on hook return; no item) |

User actions: `sendUserMessage(content)` posts `{type:'user_message', content}` AND appends `{kind:'user', content}` locally so the user sees their text immediately. `acceptProposal(id)` posts `{type:'accept_proposal', proposal_id}`. `rejectProposal(id)` posts `{type:'reject_proposal', proposal_id}`.

---

### Task 1: Extend types + Vite WS proxy

**Files:**
- Modify: `D:\agent-app-card-extractor\web\src\types.ts`
- Modify: `D:\agent-app-card-extractor\web\vite.config.ts`

No tests in this task — type changes are checked by the compiler when later tasks import them, and the Vite proxy change is exercised manually in Task 6.

- [ ] **Step 1: Append to `web/src/types.ts`**

Open `D:\agent-app-card-extractor\web\src\types.ts` and APPEND (do not replace the existing content):

```ts
// --- Chat ---

export interface Proposal {
  proposal_id: string;
  path: string;
  old_value: unknown;
  new_value: unknown;
}

export type ChatItem =
  | { kind: "user"; content: string }
  | { kind: "assistant"; content: string }
  | { kind: "tool"; summary: string }
  | { kind: "proposal"; proposal: Proposal; status: "pending" | "applied" | "rejected" };

export interface ChatHistoryRow {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tool_call_id: string | null;
}

export type ChatEvent =
  | { type: "ready"; job_id: string }
  | { type: "history"; messages: ChatHistoryRow[] }
  | { type: "assistant_message"; content: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown>; result: string }
  | ({ type: "proposal" } & Proposal)
  | { type: "applied"; proposal_id: string }
  | { type: "rejected"; proposal_id: string }
  | { type: "error"; message: string };

export type ChatStatus = "connecting" | "open" | "closed" | "error";
```

- [ ] **Step 2: Replace `web/vite.config.ts`**

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
      "/chat": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
      },
    },
  },
});
```

The `/chat` entry uses `ws://` and `ws: true` so Vite forwards the WebSocket upgrade. `changeOrigin: true` rewrites the Host header for the backend.

- [ ] **Step 3: Verify the existing test suite still passes**

```bash
cd D:\agent-app-card-extractor\web
npm test
```

Expected: 19 passed (the Plan 2 count is unchanged — types are additive and the proxy entry is only exercised at runtime).

- [ ] **Step 4: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/types.ts web/vite.config.ts
git commit -m "feat(web): chat types + Vite WS proxy entry"
```

---

### Task 2: `useChat` hook — WebSocket state machine

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\hooks\useChat.ts`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\useChat.test.ts`

The hook opens one `WebSocket` per non-null `jobId`, reduces incoming events into a `ChatItem[]` timeline, and exposes three action callbacks. On `jobId` change or unmount it closes the socket.

**Mocking strategy:** tests replace `globalThis.WebSocket` with a small mock class that captures the most-recent instance so tests can drive it (call `onmessage`, etc.) and assert on `sent` messages.

- [ ] **Step 1: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\useChat.test.ts`:

```ts
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { useChat } from "../hooks/useChat";
import type { ChatEvent } from "../types";

class MockWebSocket {
  static lastInstance: MockWebSocket | null = null;
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastInstance = this;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) this.onclose(new CloseEvent("close"));
  }

  // Test helpers
  emitOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    if (this.onopen) this.onopen(new Event("open"));
  }
  emit(event: ChatEvent): void {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(event) } as MessageEvent);
  }
}

function getSocket(): MockWebSocket {
  const s = MockWebSocket.lastInstance;
  if (s === null) throw new Error("No WebSocket instance");
  return s;
}

describe("useChat", () => {
  beforeEach(() => {
    MockWebSocket.lastInstance = null;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns idle state when jobId is null and opens no socket", () => {
    const { result } = renderHook(() => useChat(null));
    expect(result.current.status).toBe("closed");
    expect(result.current.items).toEqual([]);
    expect(MockWebSocket.lastInstance).toBeNull();
  });

  it("opens a WebSocket when jobId is provided and transitions to open on the ready event", async () => {
    const { result } = renderHook(() => useChat("abc"));
    expect(result.current.status).toBe("connecting");
    expect(MockWebSocket.lastInstance).not.toBeNull();
    expect(getSocket().url).toMatch(/\/chat\/abc$/);

    act(() => {
      getSocket().emitOpen();
      getSocket().emit({ type: "ready", job_id: "abc" });
    });
    expect(result.current.status).toBe("open");
  });

  it("renders history events as timeline items", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({
        type: "history",
        messages: [
          { role: "user", content: "hi", tool_call_id: null },
          { role: "assistant", content: "hello", tool_call_id: null },
        ],
      });
    });
    expect(result.current.items).toEqual([
      { kind: "user", content: "hi" },
      { kind: "assistant", content: "hello" },
    ]);
  });

  it("history skips system rows and renders tool rows as summaries", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({
        type: "history",
        messages: [
          { role: "system", content: "ignore me", tool_call_id: null },
          { role: "tool", content: "\"M9\"", tool_call_id: "call_1" },
        ],
      });
    });
    expect(result.current.items).toEqual([{ kind: "tool", summary: "\"M9\"" }]);
  });

  it("appends an assistant item when assistant_message arrives", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({ type: "assistant_message", content: "ok" });
    });
    expect(result.current.items).toEqual([{ kind: "assistant", content: "ok" }]);
  });

  it("appends a tool item when tool_call arrives", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({
        type: "tool_call",
        name: "read_field",
        args: { path: "extractions[0].insurance.member_id" },
        result: "\"M9\"",
      });
    });
    expect(result.current.items).toHaveLength(1);
    const item = result.current.items[0];
    expect(item.kind).toBe("tool");
    if (item.kind === "tool") {
      expect(item.summary).toContain("read_field");
      expect(item.summary).toContain("M9");
    }
  });

  it("appends a pending proposal and flips its status on applied", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({
        type: "proposal",
        proposal_id: "p1",
        path: "extractions[0].insurance.member_id",
        old_value: "OLD",
        new_value: "NEW",
      });
    });
    expect(result.current.items).toEqual([
      {
        kind: "proposal",
        proposal: {
          proposal_id: "p1",
          path: "extractions[0].insurance.member_id",
          old_value: "OLD",
          new_value: "NEW",
        },
        status: "pending",
      },
    ]);

    act(() => {
      getSocket().emit({ type: "applied", proposal_id: "p1" });
    });
    const updated = result.current.items[0];
    expect(updated.kind === "proposal" && updated.status).toBe("applied");
  });

  it("flips proposal status on rejected", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({
        type: "proposal",
        proposal_id: "p1",
        path: "x",
        old_value: null,
        new_value: "v",
      });
      getSocket().emit({ type: "rejected", proposal_id: "p1" });
    });
    const updated = result.current.items[0];
    expect(updated.kind === "proposal" && updated.status).toBe("rejected");
  });

  it("sendUserMessage appends a local user item and sends over the socket", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
    });
    act(() => {
      result.current.sendUserMessage("hello there");
    });
    expect(result.current.items).toEqual([{ kind: "user", content: "hello there" }]);
    expect(getSocket().sent).toEqual([
      JSON.stringify({ type: "user_message", content: "hello there" }),
    ]);
  });

  it("acceptProposal posts the accept_proposal frame", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
    });
    act(() => {
      result.current.acceptProposal("p1");
    });
    expect(getSocket().sent).toEqual([
      JSON.stringify({ type: "accept_proposal", proposal_id: "p1" }),
    ]);
  });

  it("rejectProposal posts the reject_proposal frame", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
    });
    act(() => {
      result.current.rejectProposal("p1");
    });
    expect(getSocket().sent).toEqual([
      JSON.stringify({ type: "reject_proposal", proposal_id: "p1" }),
    ]);
  });

  it("captures error events on the `error` field", () => {
    const { result } = renderHook(() => useChat("abc"));
    act(() => {
      getSocket().emitOpen();
      getSocket().emit({ type: "error", message: "boom" });
    });
    expect(result.current.error).toBe("boom");
  });

  it("closes the socket on unmount", () => {
    const { unmount } = renderHook(() => useChat("abc"));
    const socket = getSocket();
    expect(socket.readyState).toBe(MockWebSocket.CONNECTING);
    unmount();
    expect(socket.readyState).toBe(MockWebSocket.CLOSED);
  });

  it("opens a new socket when jobId changes and closes the previous one", async () => {
    const { result, rerender } = renderHook(({ id }: { id: string | null }) => useChat(id), {
      initialProps: { id: "abc" },
    });
    const first = getSocket();
    rerender({ id: "def" });

    await waitFor(() => expect(MockWebSocket.lastInstance?.url).toMatch(/\/chat\/def$/));
    expect(first.readyState).toBe(MockWebSocket.CLOSED);
    expect(result.current.items).toEqual([]);
  });
});
```

- [ ] **Step 2: Run, confirm failure**

```bash
cd D:\agent-app-card-extractor\web
npm test -- useChat
```

Expected: `Failed to resolve import "../hooks/useChat"`.

- [ ] **Step 3: Implement `web/src/hooks/useChat.ts`**

```ts
import { useCallback, useEffect, useReducer, useRef } from "react";
import type {
  ChatEvent,
  ChatHistoryRow,
  ChatItem,
  ChatStatus,
  Proposal,
} from "../types";

interface State {
  status: ChatStatus;
  items: ChatItem[];
  error: string | null;
}

type Action =
  | { type: "reset" }
  | { type: "setStatus"; status: ChatStatus }
  | { type: "appendItem"; item: ChatItem }
  | { type: "setProposalStatus"; proposal_id: string; status: "applied" | "rejected" }
  | { type: "setError"; message: string };

const initialState: State = { status: "closed", items: [], error: null };

function historyRowToItem(row: ChatHistoryRow): ChatItem | null {
  if (row.role === "system") return null;
  if (row.role === "user") return { kind: "user", content: row.content };
  if (row.role === "assistant") return { kind: "assistant", content: row.content };
  return { kind: "tool", summary: row.content };
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "reset":
      return initialState;
    case "setStatus":
      return { ...state, status: action.status };
    case "appendItem":
      return { ...state, items: [...state.items, action.item] };
    case "setProposalStatus":
      return {
        ...state,
        items: state.items.map((it) =>
          it.kind === "proposal" && it.proposal.proposal_id === action.proposal_id
            ? { ...it, status: action.status }
            : it,
        ),
      };
    case "setError":
      return { ...state, error: action.message };
  }
}

function chatUrl(jobId: string): string {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/chat/${encodeURIComponent(jobId)}`;
}

export interface UseChat {
  status: ChatStatus;
  items: ChatItem[];
  error: string | null;
  sendUserMessage: (content: string) => void;
  acceptProposal: (proposalId: string) => void;
  rejectProposal: (proposalId: string) => void;
}

export function useChat(jobId: string | null): UseChat {
  const [state, dispatch] = useReducer(reducer, initialState);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (jobId === null) {
      dispatch({ type: "reset" });
      return;
    }

    dispatch({ type: "reset" });
    dispatch({ type: "setStatus", status: "connecting" });

    const ws = new WebSocket(chatUrl(jobId));
    wsRef.current = ws;

    ws.onmessage = (e) => {
      let event: ChatEvent;
      try {
        event = JSON.parse(e.data) as ChatEvent;
      } catch {
        return;
      }
      handleEvent(event);
    };
    ws.onclose = () => {
      dispatch({ type: "setStatus", status: "closed" });
    };
    ws.onerror = () => {
      dispatch({ type: "setStatus", status: "error" });
    };

    function handleEvent(event: ChatEvent): void {
      switch (event.type) {
        case "ready":
          dispatch({ type: "setStatus", status: "open" });
          return;
        case "history":
          for (const row of event.messages) {
            const item = historyRowToItem(row);
            if (item !== null) dispatch({ type: "appendItem", item });
          }
          return;
        case "assistant_message":
          dispatch({ type: "appendItem", item: { kind: "assistant", content: event.content } });
          return;
        case "tool_call":
          dispatch({
            type: "appendItem",
            item: {
              kind: "tool",
              summary: `${event.name}(${JSON.stringify(event.args)}) → ${event.result}`,
            },
          });
          return;
        case "proposal": {
          const proposal: Proposal = {
            proposal_id: event.proposal_id,
            path: event.path,
            old_value: event.old_value,
            new_value: event.new_value,
          };
          dispatch({
            type: "appendItem",
            item: { kind: "proposal", proposal, status: "pending" },
          });
          return;
        }
        case "applied":
          dispatch({
            type: "setProposalStatus",
            proposal_id: event.proposal_id,
            status: "applied",
          });
          return;
        case "rejected":
          dispatch({
            type: "setProposalStatus",
            proposal_id: event.proposal_id,
            status: "rejected",
          });
          return;
        case "error":
          dispatch({ type: "setError", message: event.message });
          return;
      }
    }

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [jobId]);

  const sendUserMessage = useCallback((content: string) => {
    const ws = wsRef.current;
    if (ws === null) return;
    dispatch({ type: "appendItem", item: { kind: "user", content } });
    ws.send(JSON.stringify({ type: "user_message", content }));
  }, []);

  const acceptProposal = useCallback((proposalId: string) => {
    const ws = wsRef.current;
    if (ws === null) return;
    ws.send(JSON.stringify({ type: "accept_proposal", proposal_id: proposalId }));
  }, []);

  const rejectProposal = useCallback((proposalId: string) => {
    const ws = wsRef.current;
    if (ws === null) return;
    ws.send(JSON.stringify({ type: "reject_proposal", proposal_id: proposalId }));
  }, []);

  return {
    status: state.status,
    items: state.items,
    error: state.error,
    sendUserMessage,
    acceptProposal,
    rejectProposal,
  };
}
```

- [ ] **Step 4: Run tests, confirm pass**

```bash
cd D:\agent-app-card-extractor\web
npm test -- useChat
```

Expected: 14 passed.

Full suite check:

```bash
npm test
```

Expected: 33 passed (19 from Plan 2 + 14 useChat). If the count is off by 1–2 due to renames in earlier work, the load-bearing assertion is "useChat tests all pass and the Plan 2 tests still pass."

- [ ] **Step 5: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/hooks/useChat.ts web/src/__tests__/useChat.test.ts
git commit -m "feat(web): useChat hook — WebSocket state machine with timeline reducer"
```

---

### Task 3: `EditProposal` component

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\panes\EditProposal.tsx`
- Create: `D:\agent-app-card-extractor\web\src\panes\EditProposal.css`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\EditProposal.test.tsx`

Pure presentational. Renders the proposal's path, old value, new value, and accept/reject buttons. When `status` is `"applied"` or `"rejected"`, the buttons are replaced by a status badge.

- [ ] **Step 1: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\EditProposal.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { EditProposal } from "../panes/EditProposal";
import type { Proposal } from "../types";

function makeProposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    proposal_id: "p1",
    path: "extractions[0].insurance.member_id",
    old_value: "OLD",
    new_value: "NEW",
    ...overrides,
  };
}

describe("EditProposal", () => {
  it("renders the path and both values when pending", () => {
    render(
      <EditProposal
        proposal={makeProposal()}
        status="pending"
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.getByText(/extractions\[0\]\.insurance\.member_id/)).toBeInTheDocument();
    expect(screen.getByText(/"OLD"/)).toBeInTheDocument();
    expect(screen.getByText(/"NEW"/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
  });

  it("invokes onAccept with the proposal_id when accept is clicked", async () => {
    const onAccept = vi.fn();
    render(
      <EditProposal
        proposal={makeProposal({ proposal_id: "pX" })}
        status="pending"
        onAccept={onAccept}
        onReject={() => {}}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /accept/i }));
    expect(onAccept).toHaveBeenCalledWith("pX");
  });

  it("invokes onReject with the proposal_id when reject is clicked", async () => {
    const onReject = vi.fn();
    render(
      <EditProposal
        proposal={makeProposal({ proposal_id: "pY" })}
        status="pending"
        onAccept={() => {}}
        onReject={onReject}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(onReject).toHaveBeenCalledWith("pY");
  });

  it("hides the buttons and shows a status badge when applied", () => {
    render(
      <EditProposal
        proposal={makeProposal()}
        status="applied"
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /reject/i })).not.toBeInTheDocument();
    expect(screen.getByText(/applied/i)).toBeInTheDocument();
  });

  it("shows a rejected badge when status is rejected", () => {
    render(
      <EditProposal
        proposal={makeProposal()}
        status="rejected"
        onAccept={() => {}}
        onReject={() => {}}
      />,
    );
    expect(screen.queryByRole("button", { name: /accept/i })).not.toBeInTheDocument();
    expect(screen.getByText(/rejected/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, confirm failure**

```bash
cd D:\agent-app-card-extractor\web
npm test -- EditProposal
```

Expected: import resolution fails.

- [ ] **Step 3: Implement `web/src/panes/EditProposal.tsx`**

```tsx
import type { Proposal } from "../types";
import "./EditProposal.css";

interface Props {
  proposal: Proposal;
  status: "pending" | "applied" | "rejected";
  onAccept: (proposalId: string) => void;
  onReject: (proposalId: string) => void;
}

export function EditProposal({ proposal, status, onAccept, onReject }: Props) {
  return (
    <div className={`edit-proposal edit-proposal--${status}`}>
      <div className="edit-proposal__path">{proposal.path}</div>
      <div className="edit-proposal__diff">
        <div className="edit-proposal__row edit-proposal__row--old">
          <span className="edit-proposal__label">old</span>
          <code>{JSON.stringify(proposal.old_value)}</code>
        </div>
        <div className="edit-proposal__row edit-proposal__row--new">
          <span className="edit-proposal__label">new</span>
          <code>{JSON.stringify(proposal.new_value)}</code>
        </div>
      </div>
      {status === "pending" ? (
        <div className="edit-proposal__actions">
          <button
            type="button"
            className="edit-proposal__btn edit-proposal__btn--accept"
            onClick={() => onAccept(proposal.proposal_id)}
          >
            Accept
          </button>
          <button
            type="button"
            className="edit-proposal__btn edit-proposal__btn--reject"
            onClick={() => onReject(proposal.proposal_id)}
          >
            Reject
          </button>
        </div>
      ) : (
        <div className={`edit-proposal__badge edit-proposal__badge--${status}`}>{status}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Write `web/src/panes/EditProposal.css`**

```css
.edit-proposal {
  border: 1px solid #ccd;
  border-radius: 6px;
  padding: 0.75rem;
  background-color: #fbfbff;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.edit-proposal--applied {
  border-color: #b9e0b9;
  background-color: #f4fbf4;
}
.edit-proposal--rejected {
  border-color: #e0b9b9;
  background-color: #fbf4f4;
}
.edit-proposal__path {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.8rem;
  color: #444;
}
.edit-proposal__diff {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}
.edit-proposal__row {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
}
.edit-proposal__row code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85rem;
}
.edit-proposal__row--old code {
  color: #842525;
  text-decoration: line-through;
}
.edit-proposal__row--new code {
  color: #185c18;
}
.edit-proposal__label {
  display: inline-block;
  min-width: 2rem;
  font-size: 0.7rem;
  color: #888;
  text-transform: uppercase;
}
.edit-proposal__actions {
  display: flex;
  gap: 0.5rem;
}
.edit-proposal__btn {
  padding: 0.3rem 0.9rem;
  border-radius: 4px;
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid transparent;
}
.edit-proposal__btn--accept {
  background-color: #2a7a2a;
  color: white;
}
.edit-proposal__btn--reject {
  background-color: white;
  color: #842525;
  border-color: #d8b0b0;
}
.edit-proposal__badge {
  align-self: flex-start;
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
}
.edit-proposal__badge--applied {
  background-color: #d6f5d6;
  color: #185c18;
}
.edit-proposal__badge--rejected {
  background-color: #fadcdc;
  color: #842525;
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd D:\agent-app-card-extractor\web
npm test -- EditProposal
```

Expected: 5 passed.

Full suite: `npm test` — 19 (Plan 2) + 14 (useChat) + 5 (EditProposal) = 38.

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/panes/EditProposal.tsx web/src/panes/EditProposal.css web/src/__tests__/EditProposal.test.tsx
git commit -m "feat(web): EditProposal diff card with accept/reject + status badge"
```

---

### Task 4: `Chat` pane

**Files:**
- Create: `D:\agent-app-card-extractor\web\src\panes\Chat.tsx`
- Create: `D:\agent-app-card-extractor\web\src\panes\Chat.css`
- Test: `D:\agent-app-card-extractor\web\src\__tests__\Chat.test.tsx`

Renders the `ChatItem[]` timeline (one element per item, switching on `kind`) plus a text input + Send button at the bottom. When status is `connecting` it shows "Connecting…"; `closed` or `error` shows a small banner. Calls `onProposalAccepted(proposalId)` UP to the parent after firing `acceptProposal` so the parent can refresh the previewer.

Because `useChat` opens a real `WebSocket`, the Chat tests mock the module:

- [ ] **Step 1: Write the failing tests**

`D:\agent-app-card-extractor\web\src\__tests__\Chat.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Chat } from "../panes/Chat";
import * as useChatModule from "../hooks/useChat";
import type { UseChat } from "../hooks/useChat";
import type { ChatItem } from "../types";

function stubChat(overrides: Partial<UseChat> = {}): UseChat {
  return {
    status: "open",
    items: [],
    error: null,
    sendUserMessage: vi.fn(),
    acceptProposal: vi.fn(),
    rejectProposal: vi.fn(),
    ...overrides,
  };
}

describe("Chat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when jobId is null", () => {
    const spy = vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat());
    const { container } = render(<Chat jobId={null} onProposalAccepted={() => {}} />);
    expect(container.firstChild).toBeNull();
    expect(spy).toHaveBeenCalledWith(null);
  });

  it("renders user, assistant, and tool items in order", () => {
    const items: ChatItem[] = [
      { kind: "user", content: "hi" },
      { kind: "assistant", content: "hello" },
      { kind: "tool", summary: "read_field(...) → \"M9\"" },
    ];
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ items }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);

    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText(/read_field/)).toBeInTheDocument();
  });

  it("renders a proposal item via EditProposal", () => {
    const items: ChatItem[] = [
      {
        kind: "proposal",
        proposal: {
          proposal_id: "p1",
          path: "extractions[0].insurance.member_id",
          old_value: "OLD",
          new_value: "NEW",
        },
        status: "pending",
      },
    ];
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ items }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);

    expect(screen.getByText(/extractions\[0\]\.insurance\.member_id/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
  });

  it("calls sendUserMessage when the user submits the input", async () => {
    const sendUserMessage = vi.fn();
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ sendUserMessage }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);

    const input = screen.getByPlaceholderText(/ask the agent/i);
    await userEvent.type(input, "fix the member id");
    await userEvent.click(screen.getByRole("button", { name: /send/i }));

    expect(sendUserMessage).toHaveBeenCalledWith("fix the member id");
    expect(input).toHaveValue("");
  });

  it("does not send empty messages", async () => {
    const sendUserMessage = vi.fn();
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ sendUserMessage }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);

    await userEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(sendUserMessage).not.toHaveBeenCalled();
  });

  it("calls acceptProposal AND onProposalAccepted when accept is clicked", async () => {
    const acceptProposal = vi.fn();
    const onProposalAccepted = vi.fn();
    const items: ChatItem[] = [
      {
        kind: "proposal",
        proposal: { proposal_id: "p9", path: "x", old_value: 1, new_value: 2 },
        status: "pending",
      },
    ];
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ items, acceptProposal }));
    render(<Chat jobId="abc" onProposalAccepted={onProposalAccepted} />);

    await userEvent.click(screen.getByRole("button", { name: /accept/i }));
    expect(acceptProposal).toHaveBeenCalledWith("p9");
    expect(onProposalAccepted).toHaveBeenCalledWith("p9");
  });

  it("calls rejectProposal (but NOT onProposalAccepted) when reject is clicked", async () => {
    const rejectProposal = vi.fn();
    const onProposalAccepted = vi.fn();
    const items: ChatItem[] = [
      {
        kind: "proposal",
        proposal: { proposal_id: "p9", path: "x", old_value: 1, new_value: 2 },
        status: "pending",
      },
    ];
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ items, rejectProposal }));
    render(<Chat jobId="abc" onProposalAccepted={onProposalAccepted} />);

    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(rejectProposal).toHaveBeenCalledWith("p9");
    expect(onProposalAccepted).not.toHaveBeenCalled();
  });

  it("shows a connecting indicator when status is connecting", () => {
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ status: "connecting" }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("shows the error banner when error is set", () => {
    vi.spyOn(useChatModule, "useChat").mockReturnValue(stubChat({ error: "boom" }));
    render(<Chat jobId="abc" onProposalAccepted={() => {}} />);
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, confirm failure**

```bash
cd D:\agent-app-card-extractor\web
npm test -- Chat
```

Expected: `Failed to resolve import "../panes/Chat"`.

- [ ] **Step 3: Implement `web/src/panes/Chat.tsx`**

```tsx
import { useState } from "react";
import { useChat } from "../hooks/useChat";
import { EditProposal } from "./EditProposal";
import "./Chat.css";

interface Props {
  jobId: string | null;
  onProposalAccepted: (proposalId: string) => void;
}

export function Chat({ jobId, onProposalAccepted }: Props) {
  const chat = useChat(jobId);
  const [draft, setDraft] = useState("");

  if (jobId === null) return null;

  function submit(): void {
    const text = draft.trim();
    if (text === "") return;
    chat.sendUserMessage(text);
    setDraft("");
  }

  function handleAccept(proposalId: string): void {
    chat.acceptProposal(proposalId);
    onProposalAccepted(proposalId);
  }

  return (
    <div className="chat">
      <div className="chat__header">
        <span className="chat__title">Chat</span>
        <span className={`chat__status chat__status--${chat.status}`}>{chat.status}</span>
      </div>
      {chat.status === "connecting" && <div className="chat__connecting">Connecting…</div>}
      {chat.error !== null && <div className="chat__error">{chat.error}</div>}
      <div className="chat__timeline">
        {chat.items.map((item, idx) => {
          if (item.kind === "user") {
            return (
              <div key={idx} className="chat__msg chat__msg--user">
                {item.content}
              </div>
            );
          }
          if (item.kind === "assistant") {
            return (
              <div key={idx} className="chat__msg chat__msg--assistant">
                {item.content}
              </div>
            );
          }
          if (item.kind === "tool") {
            return (
              <div key={idx} className="chat__msg chat__msg--tool">
                {item.summary}
              </div>
            );
          }
          // proposal
          return (
            <EditProposal
              key={idx}
              proposal={item.proposal}
              status={item.status}
              onAccept={handleAccept}
              onReject={chat.rejectProposal}
            />
          );
        })}
      </div>
      <form
        className="chat__input"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <input
          type="text"
          placeholder="Ask the agent about this extraction…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit">Send</button>
      </form>
    </div>
  );
}
```

- [ ] **Step 4: Write `web/src/panes/Chat.css`**

```css
.chat {
  display: flex;
  flex-direction: column;
  border: 1px solid #ddd;
  border-radius: 8px;
  background-color: white;
  overflow: hidden;
  min-height: 24rem;
}
.chat__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 1rem;
  background-color: #f6f6f8;
  border-bottom: 1px solid #eee;
}
.chat__title {
  font-weight: 600;
  font-size: 0.95rem;
}
.chat__status {
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  background-color: #eee;
  color: #555;
}
.chat__status--open {
  background-color: #d6f5d6;
  color: #185c18;
}
.chat__status--connecting {
  background-color: #fff4cc;
  color: #7a5b00;
}
.chat__status--error {
  background-color: #fadcdc;
  color: #842525;
}
.chat__connecting {
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
  color: #7a5b00;
}
.chat__error {
  padding: 0.5rem 1rem;
  background-color: #fadcdc;
  color: #842525;
  font-size: 0.85rem;
}
.chat__timeline {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1rem;
  overflow-y: auto;
  min-height: 12rem;
  max-height: 32rem;
}
.chat__msg {
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.9rem;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat__msg--user {
  background-color: #e7efff;
  align-self: flex-end;
  max-width: 80%;
}
.chat__msg--assistant {
  background-color: #f3f3f3;
  align-self: flex-start;
  max-width: 80%;
}
.chat__msg--tool {
  background-color: #fafafa;
  border: 1px dashed #ccc;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.78rem;
  color: #555;
}
.chat__input {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-top: 1px solid #eee;
  background-color: #fafafa;
}
.chat__input input {
  flex: 1;
  padding: 0.4rem 0.6rem;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 0.9rem;
}
.chat__input button {
  padding: 0.4rem 1rem;
  background-color: #44a;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
```

- [ ] **Step 5: Run tests, confirm pass**

```bash
cd D:\agent-app-card-extractor\web
npm test -- Chat
```

Expected: 9 passed.

Full suite: `npm test` — 19 (Plan 2) + 14 (useChat) + 5 (EditProposal) + 9 (Chat) = 47.

- [ ] **Step 6: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/panes/Chat.tsx web/src/panes/Chat.css web/src/__tests__/Chat.test.tsx
git commit -m "feat(web): Chat pane with timeline + input + inline EditProposal cards"
```

---

### Task 5: Compose Chat into `App` + previewer refresh on accept

**Files:**
- Modify: `D:\agent-app-card-extractor\web\src\App.tsx`
- Modify: `D:\agent-app-card-extractor\web\src\App.css`
- Modify: `D:\agent-app-card-extractor\web\src\panes\Previewer.tsx`
- Modify: `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx`

Two changes:
1. Mount `Chat` in the right column under `Previewer` when `job.status === 'complete'`. The right column becomes a 2-row grid.
2. When the user accepts a proposal, the JSON file on disk mutates — but the Previewer was rendered once and won't re-fetch. Solution: `App` keeps a `refreshKey` integer; `onProposalAccepted` increments it; `Previewer` accepts a `refreshKey` prop and re-fetches when it changes.

- [ ] **Step 1: Modify `App.test.tsx` — add chat assertion**

Append to `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx` (inside the `describe("App")` block, after the existing tests):

```tsx
  it("mounts the chat pane only when the job is complete", async () => {
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

    // Chat mounts only when status flips to complete.
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument(),
    );
  });
```

- [ ] **Step 2: Run, confirm failure**

```bash
cd D:\agent-app-card-extractor\web
npm test -- App
```

Expected: the new test fails — App doesn't mount Chat yet AND `useChat` will attempt to open a real WebSocket in the jsdom env (which has no WebSocket constructor). The next steps wire the component in AND stub the global WebSocket for the App test.

- [ ] **Step 3: Stub `WebSocket` in the App test**

Edit `D:\agent-app-card-extractor\web\src\__tests__\App.test.tsx`. Update the top of the file to stub WebSocket globally for this suite (place this after the imports, before `describe`):

```tsx
class StubWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  readyState = StubWebSocket.CONNECTING;
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(url: string) {
    this.url = url;
  }
  send(_data: string): void {}
  close(): void {
    this.readyState = StubWebSocket.CLOSED;
    if (this.onclose) this.onclose(new CloseEvent("close"));
  }
}
```

Inside `describe("App")`, replace the existing `beforeEach` with:

```tsx
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("WebSocket", StubWebSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });
```

Add `afterEach` to the imports at the top of the file if not already present:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
```

- [ ] **Step 4: Replace `web/src/App.tsx`**

```tsx
import { useState } from "react";
import { FileDrop } from "./panes/FileDrop";
import { Previewer } from "./panes/Previewer";
import { Chat } from "./panes/Chat";
import { useJobStatus } from "./hooks/useJobStatus";

export function App() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [previewerRefreshKey, setPreviewerRefreshKey] = useState(0);
  const { job, error } = useJobStatus(jobId);
  const isComplete = job?.status === "complete";

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
          <Previewer jobId={isComplete ? jobId : null} refreshKey={previewerRefreshKey} />
          {isComplete && (
            <Chat
              jobId={jobId}
              onProposalAccepted={() => setPreviewerRefreshKey((k) => k + 1)}
            />
          )}
        </section>
      </main>
    </div>
  );
}
```

- [ ] **Step 5: Update `web/src/panes/Previewer.tsx` to honor `refreshKey`**

Replace the existing `Previewer` component. Specifically: add a `refreshKey` prop and include it in the `useEffect` dependency list so changes trigger a re-fetch.

`D:\agent-app-card-extractor\web\src\panes\Previewer.tsx`:

```tsx
import { useEffect, useState } from "react";
import { getJob, getJobXml } from "../api";
import type { Job } from "../types";
import "./Previewer.css";

interface Props {
  jobId: string | null;
  refreshKey?: number;
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

export function Previewer({ jobId, refreshKey = 0 }: Props) {
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
  }, [jobId, refreshKey]);

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

- [ ] **Step 6: Update `web/src/App.css` — right column 2-row grid**

Append to `D:\agent-app-card-extractor\web\src\App.css`:

```css
.app__pane--right {
  display: grid;
  grid-template-rows: minmax(0, 1fr) minmax(20rem, auto);
  gap: 1rem;
}
```

(The earlier `.app__pane` rule already sets `display: flex`. This override targets only the right pane so the Previewer and Chat stack with the Previewer taking remaining space and Chat keeping a minimum height. Verify no conflicting `.app__pane--right` rule exists; if there is one from Plan 2, replace it.)

- [ ] **Step 7: Run tests, confirm pass**

```bash
cd D:\agent-app-card-extractor\web
npm test
```

Expected: 48 passed (the 47 previous + 1 new App integration test).

- [ ] **Step 8: Commit**

```bash
cd D:\agent-app-card-extractor
git add web/src/App.tsx web/src/App.css web/src/panes/Previewer.tsx web/src/__tests__/App.test.tsx
git commit -m "feat(web): mount Chat under Previewer; refresh JSON after accepted edits"
```

---

### Task 6: README + manual smoke

**Files:**
- Modify: `D:\agent-app-card-extractor\README.md`

- [ ] **Step 1: Update the Status section**

Open `D:\agent-app-card-extractor\README.md` and replace the existing Status block with:

```markdown
## Status

- Plan 1 (backend): **complete** — `POST /uploads`, `GET /jobs/:id`, `GET /jobs/:id/xml`.
- Plan 2 (frontend): **complete** — file-drop pane + dual JSON/XML previewer.
- Plan 3a (chat backend): **complete** — WS `/chat/:job_id` with read/set field tools.
- Plan 3b (chat frontend): **complete** — inline chat pane + edit-proposal cards.
- Plan 4 (installer): pending.
```

- [ ] **Step 2: Add a "Chat" subsection under Dev**

Append after the existing "Tests" block:

````markdown
## Chat (Plan 3b)

Once a job is `complete`, a Chat pane appears under the Previewer.

- Type a message and press Enter (or click Send) — the agent receives it over a WebSocket.
- The agent can call `read_field` (read-only, surfaces in the timeline as a tool line) or `set_field` (proposes a change, surfaces as an inline diff card).
- Click Accept on a diff card to mutate the on-disk JSON (the Previewer auto-refreshes). Click Reject to discard.

The Vite dev proxy is configured to forward `/chat` WebSocket upgrades to the backend on `:8000`.
````

- [ ] **Step 3: Manual smoke (optional — requires a valid `AI_GATEWAY_KEY`)**

If you have a key:

1. Backend: `uv run uvicorn app.main:app --reload`
2. Frontend: `cd web && npm run dev`
3. Open `http://localhost:5173`.
4. Drop a PDF. Wait for status `complete`.
5. In the Chat pane: type "what is the member id?" and Send. Expect a tool-call line (read_field) and then an assistant answer.
6. Type "set the member id to TEST123" and Send. Expect a tool-call line, then an inline diff card with old/new values.
7. Click Accept on the card. The Previewer's JSON should refresh and show `"member_id": "TEST123"`.
8. Click Reject on a different proposal to verify it disappears without mutating the JSON.

If you don't have a key, the test suite already exercises the UI surface against mocked WS and HTTP.

- [ ] **Step 4: Commit**

```bash
cd D:\agent-app-card-extractor
git add README.md
git commit -m "docs: README — Plan 3b chat frontend complete"
```

---

## Plan 3b exit criteria

- [ ] `cd web && npm test` reports 48 tests passing (19 Plan 2 + 14 useChat + 5 EditProposal + 9 Chat + 1 App).
- [ ] `cd web && npm run build` succeeds (TypeScript compiles, Vite builds to `web/dist/`).
- [ ] `cd web && npm run dev` starts cleanly with no console errors when the backend isn't running (only WS connection errors expected on first chat attempt).
- [ ] With the backend running on `:8000` and a valid gateway key, dropping a PDF → waiting for complete → typing a message in Chat → receiving an assistant reply works end-to-end.
- [ ] An agent-proposed `set_field` shows as an inline diff card with Accept / Reject buttons.
- [ ] Clicking Accept mutates `state/outputs/<job_id>.json` (visible in the Previewer after auto-refresh) and the card flips to an "applied" badge.
- [ ] Clicking Reject flips the card to a "rejected" badge and leaves the JSON unchanged.
- [ ] No backend code under `app/` was changed in Plan 3b — the WS contract from Plan 3a is the integration point.

When all boxes are checked, Plan 3b is done. Plan 4 (PyInstaller packaging, static-asset mounting, distribution smoke) follows.
