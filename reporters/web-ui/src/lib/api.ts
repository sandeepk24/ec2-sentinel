import type { HealthPayload } from "../types";

export async function fetchHealth(): Promise<HealthPayload> {
  const resp = await fetch("/api/health", { cache: "no-store" });
  if (!resp.ok) {
    throw new Error(`Health API returned HTTP ${resp.status}`);
  }
  return resp.json();
}
