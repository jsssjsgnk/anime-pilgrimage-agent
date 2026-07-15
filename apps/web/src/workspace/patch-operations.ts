import type { VisitPlace } from "./types";

export type PlacePatchAction = "include" | "exclude" | "move_day" | "reorder";

export function buildPlacePatchOperation(
  places: VisitPlace[],
  action: PlacePatchAction,
  targetDay?: number,
  targetPosition?: number,
): { op: string; [key: string]: unknown } {
  const placeIds = [...new Set(places.map((place) => place.place_id))];
  if (placeIds.length === 0) throw new Error("请先选择地点。");
  if (action === "reorder" && placeIds.length > 1) {
    throw new Error("批量调整顺序需要逐个指定位置。");
  }
  if (placeIds.length === 1) {
    return {
      op: "place",
      action,
      place_id: placeIds[0],
      ...(targetDay ? { target_day: targetDay } : {}),
      ...(targetPosition !== undefined ? { target_position: targetPosition } : {}),
    };
  }
  return {
    op: "place_batch",
    action,
    place_ids: placeIds,
    ...(targetDay ? { target_day: targetDay } : {}),
  };
}
