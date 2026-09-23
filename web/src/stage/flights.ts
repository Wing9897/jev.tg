import type { BatchResult, HitExtract } from "../types";

export const MAX_SIMULTANEOUS_FLIGHTS = 4;

export type Flight = {
  id: string;
  kind: "hit" | "miss";
  from: DOMRect;
  to?: DOMRect;
  batch?: BatchResult;
  hit?: HitExtract;
};
