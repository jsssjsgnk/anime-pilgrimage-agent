import { describe, expect, it } from "vitest";

import { safeApiErrorMessage } from "../src/workspace/api-error";
import { buildPlacePatchOperation } from "../src/workspace/patch-operations";
import type { VisitPlace } from "../src/workspace/types";

function place(index: number): VisitPlace {
  return {
    place_id: `00000000-0000-4000-8000-${index.toString().padStart(12, "0")}`,
    canonical_name: `地点 ${index}`,
    coordinate: { latitude: 35.6, longitude: 139.7 },
    verification_status: "community",
    scene_evidence_ids: [],
    subject_appearances: [],
  };
}

describe("workspace patch boundaries", () => {
  it("serializes 109 selected places as one batch operation", () => {
    const places = Array.from({ length: 109 }, (_value, index) => place(index + 1));

    expect(buildPlacePatchOperation(places, "exclude")).toEqual({
      op: "place_batch",
      action: "exclude",
      place_ids: places.map((item) => item.place_id),
    });
  });

  it("never shows structured validation bodies to the user", async () => {
    const response = new Response(JSON.stringify({
      detail: [{
        type: "too_long",
        loc: ["body", "patch", "operations"],
        msg: "Tuple should have at most 25 items",
        input: [{ place_id: "internal-id" }],
      }],
    }), { status: 422, headers: { "Content-Type": "application/json" } });

    const message = await safeApiErrorMessage(response);

    expect(message).toBe("这次输入无法处理，请检查后重试。");
    expect(message).not.toMatch(/Tuple|operations|internal-id/u);
  });
});
