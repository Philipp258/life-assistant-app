import { describe, expect, it } from "vitest";

import { formatDoAt } from "./format";

/**
 * Regression tests for issue #82 — UTC instants must render in the
 * browser's local timezone.
 *
 * These tests are timezone-independent: they compute the expected
 * local wall-clock from the same `Date` parse the function-under-test
 * performs, then assert `formatDoAt` returns that wall-clock. The
 * point of the regression is that `new Date(iso)` actually honours
 * the `Z` / `+00:00` marker rather than treating the string as
 * already-local — that property holds in any TZ.
 */
function localHHMM(iso: string): string {
  const d = new Date(iso);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

describe("formatDoAt", () => {
  it("renders a Z-suffixed UTC instant as the matching local wall-clock", () => {
    const iso = "2099-05-07T21:25:00Z";
    const out = formatDoAt(iso);
    expect(out).toMatch(new RegExp(`${localHHMM(iso)}$`));
  });

  it("renders the same instant whether the input is `Z` or `+00:00`", () => {
    expect(formatDoAt("2099-05-07T21:25:00Z")).toBe(
      formatDoAt("2099-05-07T21:25:00+00:00"),
    );
  });

  it("uses 24-hour, zero-padded time", () => {
    const iso = "2099-01-01T05:07:00Z";
    const out = formatDoAt(iso);
    // Whatever local TZ we're in, the hours and minutes must be 2-digit.
    expect(out).toMatch(/\b\d{2}:\d{2}\b/);
    expect(out).toMatch(new RegExp(`${localHHMM(iso)}\\b`));
  });
});
