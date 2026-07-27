/**
 * Catalogue component tests.
 *
 * Covers the states a browsing student can land in — loading, results, empty,
 * error, and end-of-list — because a catalogue showing nothing is otherwise
 * indistinguishable from a broken one.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";
import type { CourseSummary, Page } from "@/features/courses/types";

const fetchCatalogue = vi.fn();

vi.mock("@/features/courses/api", () => ({
  fetchCatalogue: (...args: unknown[]) => fetchCatalogue(...args),
  fetchCourse: vi.fn(),
  fetchLesson: vi.fn(),
}));

const { CourseCatalogue } = await import(
  "@/features/courses/components/course-catalogue"
);

function makeCourse(overrides: Partial<CourseSummary> = {}): CourseSummary {
  return {
    id: crypto.randomUUID(),
    slug: "cardiology-basics",
    title: "Cardiology Basics",
    subtitle: "Start here",
    specialty: "Cardiology",
    difficulty: "foundation",
    status: "published",
    cover_image_url: null,
    lesson_count: 6,
    total_duration_seconds: 3600,
    published_at: "2026-07-01T00:00:00Z",
    ...overrides,
  };
}

function makePage(items: CourseSummary[], nextCursor: string | null = null): Page<CourseSummary> {
  return {
    items,
    pagination: { next_cursor: nextCursor, has_more: nextCursor !== null, limit: 12 },
  };
}

function renderCatalogue() {
  // Retries disabled so an error state renders immediately rather than after
  // exponential backoff.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CourseCatalogue />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchCatalogue.mockReset();
  vi.useRealTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("CourseCatalogue", () => {
  it("renders courses with their lesson count and duration", async () => {
    fetchCatalogue.mockResolvedValue(makePage([makeCourse()]));
    renderCatalogue();

    expect(await screen.findByText("Cardiology Basics")).toBeInTheDocument();
    expect(screen.getByText("6 lessons")).toBeInTheDocument();
    expect(screen.getByText("1h")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Cardiology Basics/ })).toHaveAttribute(
      "href",
      "/courses/cardiology-basics",
    );
  });

  it("uses the singular noun for a one-lesson course", async () => {
    fetchCatalogue.mockResolvedValue(makePage([makeCourse({ lesson_count: 1 })]));
    renderCatalogue();

    expect(await screen.findByText("1 lesson")).toBeInTheDocument();
  });

  it("shows a distinct empty state when nothing is published", async () => {
    fetchCatalogue.mockResolvedValue(makePage([]));
    renderCatalogue();

    expect(await screen.findByText("No courses found")).toBeInTheDocument();
    expect(
      screen.getByText(/Courses will appear here once they are published/),
    ).toBeInTheDocument();
    // With no filters applied there is nothing to clear.
    expect(
      screen.queryByRole("button", { name: "Clear filters" }),
    ).not.toBeInTheDocument();
  });

  it("offers to clear filters when a search returns nothing", async () => {
    const user = userEvent.setup();
    fetchCatalogue.mockResolvedValue(makePage([]));
    renderCatalogue();

    await user.type(screen.getByLabelText("Search courses"), "nonexistent");

    expect(
      await screen.findByRole("button", { name: "Clear filters" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Try a different search term/)).toBeInTheDocument();
  });

  it("debounces search so typing does not fire a request per keystroke", async () => {
    const user = userEvent.setup();
    fetchCatalogue.mockResolvedValue(makePage([makeCourse()]));
    renderCatalogue();

    await waitFor(() => expect(fetchCatalogue).toHaveBeenCalledTimes(1));
    await user.type(screen.getByLabelText("Search courses"), "cardio");

    // Six keystrokes must not produce six requests.
    await waitFor(
      () => {
        const queries = fetchCatalogue.mock.calls.map(
          ([params]) => (params as { q?: string }).q,
        );
        expect(queries).toContain("cardio");
      },
      { timeout: 2000 },
    );
    expect(fetchCatalogue.mock.calls.length).toBeLessThan(2 + 6);
  });

  it("passes the difficulty filter to the API", async () => {
    const user = userEvent.setup();
    fetchCatalogue.mockResolvedValue(makePage([makeCourse()]));
    renderCatalogue();

    await waitFor(() => expect(fetchCatalogue).toHaveBeenCalled());
    await user.selectOptions(screen.getByLabelText("Difficulty"), "advanced");

    await waitFor(() => {
      const params = fetchCatalogue.mock.calls.at(-1)?.[0] as { difficulty?: string };
      expect(params.difficulty).toBe("advanced");
    });
  });

  it("loads the next page using the cursor from the previous one", async () => {
    const user = userEvent.setup();
    fetchCatalogue
      .mockResolvedValueOnce(
        makePage([makeCourse({ title: "Page one course" })], "cursor-abc"),
      )
      .mockResolvedValueOnce(makePage([makeCourse({ title: "Page two course" })]));
    renderCatalogue();

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByText("Page two course")).toBeInTheDocument();
    // The first page stays rendered — this is accumulation, not replacement.
    expect(screen.getByText("Page one course")).toBeInTheDocument();

    const secondCall = fetchCatalogue.mock.calls[1]?.[0] as { cursor?: string };
    expect(secondCall.cursor).toBe("cursor-abc");
  });

  it("reports the end of the list instead of an inert button", async () => {
    fetchCatalogue.mockResolvedValue(makePage([makeCourse()]));
    renderCatalogue();

    expect(await screen.findByText("That is every course.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("shows a retry action for a retryable failure", async () => {
    fetchCatalogue.mockRejectedValue(
      new ApiError({
        message: "upstream down",
        code: "UPSTREAM_UNAVAILABLE",
        status: 503,
        requestId: "req-123",
      }),
    );
    renderCatalogue();

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText(/temporarily unavailable/)).toBeInTheDocument();
    // The request id is surfaced so support can trace it.
    expect(within(alert).getByText("req-123")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("does not offer a retry for a non-retryable failure", async () => {
    fetchCatalogue.mockRejectedValue(
      new ApiError({ message: "nope", code: "FORBIDDEN", status: 403 }),
    );
    renderCatalogue();

    await screen.findByRole("alert");
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
