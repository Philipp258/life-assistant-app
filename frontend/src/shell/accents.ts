export type AccentKey = "sky" | "amber" | "sage" | "rose";

export const ACCENTS: Record<
  AccentKey,
  { c: string; soft: string; name: string }
> = {
  sky: { c: "#6E92B8", soft: "#D8E4EF", name: "Sky" },
  amber: { c: "#D97742", soft: "#F5E4D1", name: "Amber" },
  sage: { c: "#7A9A7E", soft: "#DDE8DE", name: "Sage" },
  rose: { c: "#C77A7A", soft: "#EFD7D7", name: "Rose" },
};

export const DEFAULT_ACCENT: AccentKey = "sky";
