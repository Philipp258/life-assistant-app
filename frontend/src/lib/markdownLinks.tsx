import type { AnchorHTMLAttributes, MouseEvent } from "react";
import { defaultUrlTransform } from "react-markdown";
import { useNavigate } from "react-router-dom";

import { cn } from "@/lib/utils";

const SUPPORTED_EXTERNAL_PROTOCOLS = new Set([
  "http:",
  "https:",
  "mailto:",
  "tel:",
]);
const PROTOCOL_RE = /^[a-z][a-z0-9+.-]*:/i;

function knowledgeRouteFromSegments(segments: string[]): string | null {
  const cleaned = segments.filter(
    (segment, index) => segment !== "" || index > 0,
  );
  if (cleaned.length === 0) return null;
  return `/know/open/${cleaned.map(encodeURIComponent).join("/")}`;
}

export function knowledgeRouteForPath(path: string): string | null {
  const normalized = path.replace(/^\/+/, "");
  if (!normalized) return null;
  return knowledgeRouteFromSegments(normalized.split("/"));
}

export function markdownUrlTransform(url: string): string {
  return defaultUrlTransform(url);
}

function hasModifiedClick(event: MouseEvent<HTMLAnchorElement>) {
  return (
    event.button !== 0 ||
    event.metaKey ||
    event.altKey ||
    event.ctrlKey ||
    event.shiftKey
  );
}

function internalRouteForHref(href: string): string | null {
  if (href.startsWith("/") && !href.startsWith("//")) return href;
  if (!PROTOCOL_RE.test(href)) return null;

  try {
    const url = new URL(href, window.location.href);
    if (url.origin === window.location.origin) {
      return `${url.pathname}${url.search}${url.hash}`;
    }
  } catch {
    return null;
  }

  return null;
}

function isUnsupportedCustomProtocol(href: string) {
  if (!PROTOCOL_RE.test(href)) return false;

  try {
    const url = new URL(href, window.location.href);
    return (
      url.protocol !== "" &&
      !SUPPORTED_EXTERNAL_PROTOCOLS.has(url.protocol) &&
      url.origin !== window.location.origin
    );
  } catch {
    return false;
  }
}

export function MarkdownLink({
  className,
  href,
  onClick,
  rel,
  target,
  ...props
}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const navigate = useNavigate();
  const internalRoute =
    typeof href === "string" ? internalRouteForHref(href) : null;
  const blocksCustomProtocol =
    typeof href === "string" && isUnsupportedCustomProtocol(href);
  const blocksEmptyHref = href === "";

  const handleClick = (event: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(event);
    if (event.defaultPrevented || hasModifiedClick(event)) return;
    if (target && target !== "_self") return;

    if (internalRoute) {
      event.preventDefault();
      navigate(internalRoute);
      return;
    }

    if (blocksCustomProtocol || blocksEmptyHref) {
      event.preventDefault();
    }
  };

  return (
    <a
      className={cn(
        "aui-md-a text-primary underline underline-offset-2 hover:text-primary/80",
        (blocksCustomProtocol || blocksEmptyHref) &&
          "cursor-not-allowed opacity-70",
        className,
      )}
      href={href}
      onClick={handleClick}
      target={target}
      rel={target === "_blank" ? (rel ?? "noreferrer") : rel}
      {...props}
    />
  );
}
