import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TabBar } from "./TabBar";

describe("TabBar", () => {
  it("renders the tab labels", () => {
    render(
      <MemoryRouter>
        <TabBar />
      </MemoryRouter>,
    );

    for (const label of ["Chat", "Goals", "Tasks", "Knowledge", "Agent"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual([
      "Chat",
      "Tasks",
      "Goals",
      "Knowledge",
      "Agent",
    ]);
  });

  it("restores the last task list URL when returning from Chat", async () => {
    function Probe() {
      const location = useLocation();
      return <div data-testid="location">{location.pathname}{location.search}</div>;
    }

    render(
      <MemoryRouter initialEntries={["/tasks?view=2&statuses=open&assignee=user"]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <Probe />
                <TabBar />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByText("Chat"));
    expect(screen.getByTestId("location")).toHaveTextContent("/chat");

    await userEvent.click(screen.getByText("Tasks"));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/tasks?view=2&statuses=open&assignee=user",
    );
  });
});
