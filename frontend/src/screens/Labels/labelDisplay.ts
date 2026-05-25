import type { Label } from "./labelsApi";

const LEGACY_LABEL_NAMES: Record<string, string> = {
  "improve-life-assistant": "Improve the assistant",
};

export function labelDisplayName(label: Pick<Label, "slug" | "name">): string {
  return LEGACY_LABEL_NAMES[label.slug] ?? label.name;
}

export function labelSlugDisplay(slug: string): string {
  return LEGACY_LABEL_NAMES[slug] ?? `#${slug}`;
}
