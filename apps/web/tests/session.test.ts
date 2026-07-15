import { describe, expect, it } from "vitest";

import { getWorkspaceSession } from "../src/workspace/session";

describe("development workspace session", () => {
  it("keeps a stable isolated thread in browser session storage", () => {
    const storage = window.sessionStorage;
    storage.clear();
    const root = document.createElement("div");
    const first = getWorkspaceSession(storage, root);
    const second = getWorkspaceSession(storage, root);
    expect(second).toEqual(first);
    expect(first.threadId).toMatch(/^web-/u);
    expect(first.tripStorageKey).toContain(first.threadId);
  });

  it("accepts an authenticated shell identity without component changes", () => {
    const storage = window.sessionStorage;
    storage.clear();
    const root = document.createElement("div");
    root.dataset.pilgrimageOwnerId = "signed-in-owner";
    root.dataset.pilgrimageThreadId = "signed-in-thread";
    expect(getWorkspaceSession(storage, root)).toMatchObject({
      ownerUserId: "signed-in-owner",
      threadId: "signed-in-thread",
    });
  });
});
