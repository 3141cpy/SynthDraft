import { describe, expect, it } from "vitest";
import {
  formatBoundingBox,
  formatElapsed,
  formatElapsedFromMeta,
  formatNumber,
  formatSize,
  getExtension,
} from "./format";

describe("formatElapsed", () => {
  it("ms < 1000 显示为毫秒", () => {
    expect(formatElapsed(0)).toBe("0 ms");
    expect(formatElapsed(1)).toBe("1 ms");
    expect(formatElapsed(500)).toBe("500 ms");
    expect(formatElapsed(999)).toBe("999 ms");
  });

  it("ms >= 1000 显示为秒（保留两位小数）", () => {
    expect(formatElapsed(1000)).toBe("1.00 s");
    expect(formatElapsed(1500)).toBe("1.50 s");
    expect(formatElapsed(60000)).toBe("60.00 s");
  });

  it("ms = 0 返回 '0 ms'", () => {
    expect(formatElapsed(0)).toBe("0 ms");
  });

  it("负数 ms 仍按 < 1000 分支处理（保留历史行为）", () => {
    // 任意负数都满足 < 1000，因此始终走 ms 分支
    expect(formatElapsed(-1)).toBe("-1 ms");
    expect(formatElapsed(-500)).toBe("-500 ms");
    expect(formatElapsed(-1000)).toBe("-1000 ms");
    expect(formatElapsed(-1500)).toBe("-1500 ms");
  });

  it("字符串输入：非空原样返回，空字符串返回 '-'", () => {
    expect(formatElapsed("1.23s")).toBe("1.23s");
    expect(formatElapsed("")).toBe("-");
  });

  it("undefined / null / 其他类型返回 '-'", () => {
    expect(formatElapsed(undefined)).toBe("-");
    expect(formatElapsed(null)).toBe("-");
    expect(formatElapsed({})).toBe("-");
    expect(formatElapsed([])).toBe("-");
  });
});

describe("formatElapsedFromMeta", () => {
  it("优先读取 elapsed_ms", () => {
    expect(formatElapsedFromMeta({ elapsed_ms: 500 })).toBe("500 ms");
    expect(formatElapsedFromMeta({ elapsed_ms: 1500 })).toBe("1.50 s");
  });

  it("elapsed_ms 缺失时回退到 elapsed", () => {
    expect(formatElapsedFromMeta({ elapsed: 250 })).toBe("250 ms");
    expect(formatElapsedFromMeta({ elapsed: "2.5s" })).toBe("2.5s");
  });

  it("两个字段都缺失时返回 '-'", () => {
    expect(formatElapsedFromMeta({})).toBe("-");
    expect(formatElapsedFromMeta({ foo: 1 })).toBe("-");
  });
});

describe("formatSize", () => {
  it("0 bytes 返回 '0 B'", () => {
    expect(formatSize(0)).toBe("0 B");
  });

  it("< 1024 显示为字节", () => {
    expect(formatSize(1)).toBe("1 B");
    expect(formatSize(1023)).toBe("1023 B");
  });

  it("1024 bytes 显示为 KB", () => {
    expect(formatSize(1024)).toBe("1.0 KB");
  });

  it("1048576 bytes (1 MB) 显示为 MB", () => {
    expect(formatSize(1048576)).toBe("1.00 MB");
  });

  it("1073741824 bytes (1 GB) 显示为 GB", () => {
    expect(formatSize(1073741824)).toBe("1.00 GB");
  });
});

describe("formatNumber", () => {
  it("默认保留 2 位小数", () => {
    expect(formatNumber(1.2345)).toBe("1.23");
    expect(formatNumber(1)).toBe("1.00");
  });

  it("可指定小数位数", () => {
    expect(formatNumber(3.14159, 3)).toBe("3.142");
    expect(formatNumber(3.14159, 0)).toBe("3");
  });

  it("NaN 返回 '-'", () => {
    expect(formatNumber(NaN)).toBe("-");
    expect(formatNumber(NaN, 3)).toBe("-");
  });

  it("Infinity 返回 '-'", () => {
    expect(formatNumber(Infinity)).toBe("-");
    expect(formatNumber(-Infinity)).toBe("-");
  });
});

describe("getExtension", () => {
  it("返回小写扩展名（不含点）", () => {
    expect(getExtension("file.png")).toBe("png");
    expect(getExtension("file.PNG")).toBe("png");
    expect(getExtension("archive.tar.gz")).toBe("gz");
    expect(getExtension("a.b.c.d")).toBe("d");
  });

  it("无扩展名返回空字符串", () => {
    expect(getExtension("Makefile")).toBe("");
    expect(getExtension("file")).toBe("");
  });

  it("以点开头的隐藏文件视为无扩展名", () => {
    expect(getExtension(".bashrc")).toBe("");
  });

  it("以点结尾的文件名视为无扩展名", () => {
    expect(getExtension("file.")).toBe("");
  });
});

describe("formatBoundingBox", () => {
  it("6-tuple 形态：返回 'DX × DY × DZ mm'", () => {
    const bb: [number, number, number, number, number, number] = [
      0, 0, 0, 10, 20, 30,
    ];
    expect(formatBoundingBox(bb)).toBe("10.000 × 20.000 × 30.000 mm");
  });

  it("min/max 形态：返回 'DX × DY × DZ mm'", () => {
    const bb = {
      min: [0, 0, 0] as [number, number, number],
      max: [10, 20, 30] as [number, number, number],
    };
    expect(formatBoundingBox(bb)).toBe("10.000 × 20.000 × 30.000 mm");
  });

  it("null 返回 '-'", () => {
    expect(formatBoundingBox(null)).toBe("-");
  });

  it("undefined 返回 '-'", () => {
    expect(formatBoundingBox(undefined)).toBe("-");
  });

  it("长度不足的数组返回 '-'", () => {
    expect(formatBoundingBox([1, 2, 3])).toBe("-");
    expect(formatBoundingBox([1, 2, 3, 4, 5])).toBe("-");
  });

  it("包含 NaN 的 6-tuple 返回 '-'", () => {
    expect(formatBoundingBox([0, 0, 0, NaN, 20, 30])).toBe("-");
  });

  it("非数组、非对象返回 '-'", () => {
    expect(formatBoundingBox("not a bbox")).toBe("-");
    expect(formatBoundingBox(42)).toBe("-");
  });

  it("min/max 字段非数组返回 '-'", () => {
    expect(formatBoundingBox({ min: "x", max: "y" })).toBe("-");
  });
});
