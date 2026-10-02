import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, inr, session } from "./api";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

describe("api client", () => {
  it("sends auth and organization headers", async () => {
    session.token = "tok"; session.orgId = "7";
    const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { headers: { "content-type": "application/json" } }));
    await api("/customers");
    const h = f.mock.calls[0][1]!.headers as Headers;
    expect(h.get("Authorization")).toBe("Bearer tok");
    expect(h.get("X-Organization-ID")).toBe("7");
  });

  it("turns FastAPI validation errors into readable messages", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(
      JSON.stringify({ detail: [{ loc: ["body", "gstin"], msg: "Invalid GSTIN format" }] }), { status: 422 }));
    await expect(api("/customers", { method: "POST", json: {} })).rejects.toEqual(new ApiError(422, "gstin: Invalid GSTIN format"));
  });

  it("formats INR", () => {
    expect(inr("123456.5")).toContain("1,23,456.50");
  });
});
