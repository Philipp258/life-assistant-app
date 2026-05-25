import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { MarkdownView } from "@/components/MarkdownView";

import { knowledgeRouteForPath, MarkdownLink } from "./markdownLinks";

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderLink(href: string) {
  render(
    <MemoryRouter initialEntries={["/chat"]}>
      <MarkdownLink href={href}>open</MarkdownLink>
      <Routes>
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("knowledge markdown links", () => {
  it("builds the same route format used by the knowledge screen", () => {
    expect(knowledgeRouteForPath("Projects/Life Assistant MVP Roadmap.md")).toBe(
      "/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md",
    );
  });

  it("navigates supported knowledge routes through React Router", async () => {
    renderLink("/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md");

    const link = screen.getByRole("link", { name: "open" });
    expect(link).toHaveAttribute(
      "href",
      "/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md",
    );

    await userEvent.click(link);

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/know/open/Projects/Life%20Assistant%20MVP%20Roadmap.md",
    );
  });

  it("navigates normal internal links through React Router", async () => {
    renderLink("/tasks/123");

    const link = screen.getByRole("link", { name: "open" });
    expect(link).toHaveAttribute("href", "/tasks/123");

    await userEvent.click(link);

    expect(screen.getByTestId("location")).toHaveTextContent("/tasks/123");
  });

  it("leaves allowed external protocols as normal links", () => {
    renderLink("https://example.com/docs");

    const link = screen.getByRole("link", { name: "open" });
    expect(link).toHaveAttribute("href", "https://example.com/docs");
  });

  it("blocks unsupported custom protocol navigation", async () => {
    renderLink("unknownapp://Projects/Life%20Assistant%20MVP%20Roadmap.md");

    const link = screen.getByRole("link", { name: "open" });
    expect(link).toHaveAttribute(
      "href",
      "unknownapp://Projects/Life%20Assistant%20MVP%20Roadmap.md",
    );

    await userEvent.click(link);

    expect(screen.getByTestId("location")).toHaveTextContent("/chat");
  });

  it("navigates supported knowledge routes rendered from markdown", async () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <MarkdownView source="[Roadmap](/know/open/Projects/Roadmap.md)" />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "Roadmap" });
    expect(link).toHaveAttribute("href", "/know/open/Projects/Roadmap.md");

    await userEvent.click(link);

    expect(screen.getByTestId("location")).toHaveTextContent(
      "/know/open/Projects/Roadmap.md",
    );
  });

  it("blocks unsupported custom protocol links rendered from markdown", async () => {
    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <MarkdownView source="[Roadmap](unknownapp://Projects/Roadmap.md)" />
        <Routes>
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    const link = screen.getByText("Roadmap").closest("a");
    expect(link).toHaveAttribute("href", "");

    await userEvent.click(link!);

    expect(screen.getByTestId("location")).toHaveTextContent("/chat");
  });
});
