export interface WorkspaceSession {
  ownerUserId: string;
  threadId: string;
  tripStorageKey: string;
}

const OWNER_STORAGE_KEY = "pilgrimage-development-owner";
const THREAD_STORAGE_KEY = "pilgrimage-development-thread";

function generatedThreadId(): string {
  const suffix = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `web-${suffix}`;
}

/**
 * Development session boundary.  A future authenticated shell can inject the
 * two data attributes without changing the workspace component or API calls.
 */
export function getWorkspaceSession(
  storage: Storage = window.sessionStorage,
  root: HTMLElement = document.documentElement,
): WorkspaceSession {
  const injectedOwner = root.dataset.pilgrimageOwnerId?.trim();
  const injectedThread = root.dataset.pilgrimageThreadId?.trim();
  const ownerUserId = injectedOwner || storage.getItem(OWNER_STORAGE_KEY) || "development-user";
  const threadId = injectedThread || storage.getItem(THREAD_STORAGE_KEY) || generatedThreadId();
  storage.setItem(OWNER_STORAGE_KEY, ownerUserId);
  storage.setItem(THREAD_STORAGE_KEY, threadId);
  return {
    ownerUserId,
    threadId,
    tripStorageKey: `pilgrimage-workspace-v2:${ownerUserId}:${threadId}`,
  };
}
