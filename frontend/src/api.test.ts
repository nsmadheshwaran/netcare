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

  it("refreshes an expired session once and retries the request", async () => {
    session.token = "old"; session.refresh = "r1"; session.orgId = "1";
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "content-type": "application/json" } });
    const f = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ detail: "expired" }, 401))
      .mockResolvedValueOnce(json({ access_token: "new", refresh_token: "r2" }))
      .mockResolvedValueOnce(json({ ok: true }));
    expect(await api("/customers")).toEqual({ ok: true });
    expect(f.mock.calls[1][0]).toBe("/api/v1/auth/refresh");
    expect((f.mock.calls[2][1]!.headers as Headers).get("Authorization")).toBe("Bearer new");
    expect(session.refresh).toBe("r2");
  });

  it("signs out when the refresh token is no longer valid", async () => {
    session.token = "old"; session.refresh = "r1";
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 401 }));
    await expect(api("/customers")).rejects.toBeInstanceOf(ApiError);
    expect(session.token).toBeNull();
    expect(session.refresh).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
    vi.unstubAllGlobals();
  });

  it("formats INR", () => {
    expect(inr("123456.5")).toContain("1,23,456.50");
  });
});
