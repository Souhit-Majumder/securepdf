import { describe, it, expect } from "vitest";
import { probeWebGLSupport } from "../utils/webglCheck";

describe("WebGL Hardware Probe", () => {
  it("executes probe without throwing and returns sanitized diagnostic structure", () => {
    const info = probeWebGLSupport();
    expect(info).toBeDefined();
    expect(["unsupported", "context_lost", "init_failed"]).toContain(info.status);
    expect(typeof info.webgl1_supported).toBe("boolean");
    expect(typeof info.webgl2_supported).toBe("boolean");
    expect(typeof info.error_code).toBe("string");
    expect(typeof info.message).toBe("string");
  });
});
