import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

function renderAt(path: string) {
  window.history.replaceState({}, "", path);
  return render(<App />);
}

describe("App shell", () => {
  it("redirects / to /chats", async () => {
    renderAt("/");

    await waitFor(() => expect(window.location.pathname).toBe("/chats"));
    expect(screen.getByRole("link", { name: "Чаты" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("renders both top-level tabs", () => {
    renderAt("/chats");

    const navigation = screen.getByRole("navigation", { name: "Разделы" });
    expect(navigation).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Чаты" })).toHaveAttribute(
      "href",
      "/chats",
    );
    expect(
      screen.getByRole("link", { name: "Сохранённые отчёты" }),
    ).toHaveAttribute("href", "/saved");
  });

  it("marks the saved-reports tab current on /saved/:reportId", () => {
    renderAt("/saved/r1");

    expect(
      screen.getByRole("link", { name: "Сохранённые отчёты" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Чаты" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("keeps the chats tab current on /chats/:chatId", () => {
    renderAt("/chats/c1");

    expect(screen.getByRole("link", { name: "Чаты" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
