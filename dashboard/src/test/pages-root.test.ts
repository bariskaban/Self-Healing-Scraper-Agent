import { createElement } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PagesRoot } from "@/components/pages/PagesRoot";
import { demoDashboard } from "@/data/demo";
import { downloadText, toCsv } from "@/components/pages/tenderRows";

const app = () => render(createElement(PagesRoot, null, createElement("p", null, "overview app")));
const key = (k: string, target: Element | Window = window) => fireEvent.keyDown(target, { key: k });
const go = async (hash: string) => {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
};

describe("page routing and the TV shortcuts", () => {
  beforeEach(async () => {
    // No API in the test run: every read fails, so the pages show the bundled demo snapshot.
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 404 })));
    window.history.replaceState(null, "", "/");
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("leaves every other route to the overview app", () => {
    app();
    expect(screen.getByText("overview app")).toBeInTheDocument();
  });

  it("opens the wallboard on T and leaves it on Escape, back where it came from", async () => {
    app();
    await go("#/scale");
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/portal|recipe/i));
    await act(async () => { key("t"); });
    expect(window.location.hash).toBe("#/tv");
    await go("#/tv");
    expect(screen.getByRole("heading", { name: "Watchtower TV mode" })).toBeInTheDocument();
    expect(screen.queryByText("overview app")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    await act(async () => { key("Escape"); });
    expect(window.location.hash).toBe("#/scale");
  });

  it("T also leaves the wallboard, to the overview when it was opened directly", async () => {
    window.history.replaceState(null, "", "/#/tv");
    app();
    expect(screen.getByRole("heading", { name: "Watchtower TV mode" })).toBeInTheDocument();
    await act(async () => { key("T"); });
    expect(window.location.hash).toBe("#/");
  });

  it("starts in the wallboard with ?tv=1 and drops the switch on leaving", async () => {
    window.history.replaceState(null, "", "/?tv=1");
    app();
    expect(screen.getByRole("heading", { name: "Watchtower TV mode" })).toBeInTheDocument();
    await act(async () => { key("Escape"); });
    expect(window.location.search).toBe("");
    expect(screen.getByText("overview app")).toBeInTheDocument();
  });

  it("ignores T while typing and with a modifier key", async () => {
    app();
    await go("#/tenders");
    const search = await screen.findByRole("searchbox", { name: "Search by title or buyer" });
    await act(async () => { key("t", search); });
    expect(window.location.hash).toBe("#/tenders");
    await act(async () => { fireEvent.keyDown(window, { key: "t", ctrlKey: true }); });
    expect(window.location.hash).toBe("#/tenders");
  });

  it("shows the demo tenders, narrows them by search and status, and says how many the export holds", async () => {
    window.history.replaceState(null, "", "/?demo"); // the snapshot is shown only when asked for
    app();
    await go("#/tenders");
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("13 tenders. The export holds all of them."));
    expect(screen.getByRole("link", { name: /Wartung von Lüftungsanlagen in Schulen/ })).toHaveAttribute("href", "https://evergabe.nrw.de/notices/NW-7821");
    expect(screen.getAllByRole("link", { name: "tenderned.nl" })[0]).toHaveAttribute("href", "#/portal/tn");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "stadt" } });
    expect(screen.getByRole("status")).toHaveTextContent(/^\d+ of 13 tenders match\. The export holds these \d+\.$/);
    fireEvent.click(screen.getByRole("button", { name: "Withdrawn" }));
    expect(screen.getByText("No tender matches these filters.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download CSV/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Clear filters/ }));
    expect(screen.getByRole("button", { name: /Download JSON/ })).toBeEnabled();
  });

  it("marks every assumption on the scale page and projects from the demo numbers", async () => {
    window.history.replaceState(null, "", "/?demo"); // the snapshot is shown only when asked for
    app();
    await go("#/scale");
    await waitFor(() => expect(screen.getByRole("heading", { name: /From 8 portals to 4,500/ })).toBeInTheDocument());
    expect(screen.getAllByText("Assumption").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText("2 portals on vmstart share one recipe.")).toBeInTheDocument();
    const slider = screen.getByRole("slider");
    expect(slider).toHaveValue(String(Math.round((1 / 7) * 100)));
    fireEvent.change(slider, { target: { value: "80" } });
    expect(screen.getByText(/with 80% of them on known software/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Back to observed 14%/ })).toBeInTheDocument();
    expect(demoDashboard.portals).toHaveLength(8);
  });
});

describe("export", () => {
  it("saves from memory through an object URL, with no request", () => {
    const create = vi.fn(() => "blob:x"), revoke = vi.fn();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const clicked: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(`${this.download}|${this.href}`); });
    downloadText("tenders.csv", "text/csv;charset=utf-8", toCsv([]));
    expect(create).toHaveBeenCalledTimes(1);
    expect((create.mock.calls[0] as unknown[])[0]).toBeInstanceOf(Blob);
    expect(clicked).toEqual(["tenders.csv|blob:x"]);
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(document.querySelector("a[download]")).toBeNull();
    click.mockRestore();
    vi.unstubAllGlobals();
  });
});
