"use client";

import { SearchX } from "lucide-react";
import * as React from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { CourseCard } from "@/features/courses/components/course-card";
import { useCatalogue } from "@/features/courses/hooks/use-catalogue";
import {
  DIFFICULTY_LABELS,
  type CatalogueQuery,
  type Difficulty,
} from "@/features/courses/types";

const DIFFICULTIES = Object.keys(DIFFICULTY_LABELS) as Difficulty[];
const SEARCH_DEBOUNCE_MS = 300;

/**
 * The browsable course catalogue.
 *
 * Search is debounced so a five-character query issues one request rather than
 * five. Loading, empty, error, and end-of-list are all rendered explicitly — a
 * catalogue that shows nothing when a filter matches nothing is
 * indistinguishable from one that is broken.
 */
export function CourseCatalogue() {
  const [searchInput, setSearchInput] = React.useState("");
  const [debouncedSearch, setDebouncedSearch] = React.useState("");
  const [difficulty, setDifficulty] = React.useState<Difficulty | "">("");

  React.useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const filters: CatalogueQuery = React.useMemo(
    () => ({
      ...(debouncedSearch.trim().length > 0 ? { q: debouncedSearch.trim() } : {}),
      ...(difficulty !== "" ? { difficulty } : {}),
    }),
    [debouncedSearch, difficulty],
  );

  const {
    data,
    isPending,
    isError,
    error,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    refetch,
    isRefetching,
  } = useCatalogue(filters);

  const courses = data?.pages.flatMap((page) => page.items) ?? [];
  const hasFilters = Object.keys(filters).length > 0;

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
        <div className="space-y-2">
          <Label htmlFor="catalogue-search">Search courses</Label>
          <Input
            id="catalogue-search"
            type="search"
            placeholder="Search by title or specialty…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="catalogue-difficulty">Difficulty</Label>
          <Select
            id="catalogue-difficulty"
            value={difficulty}
            onChange={(event) => setDifficulty(event.target.value as Difficulty | "")}
          >
            <option value="">All levels</option>
            {DIFFICULTIES.map((level) => (
              <option key={level} value={level}>
                {DIFFICULTY_LABELS[level]}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {isPending ? <CatalogueSkeleton /> : null}

      {isError ? (
        <div className="space-y-4">
          <Alert variant="destructive" title="We could not load the catalogue">
            {error.userMessage}
            {error.requestId !== null ? (
              <p className="mt-2 text-xs opacity-80">
                Reference: <code>{error.requestId}</code>
              </p>
            ) : null}
          </Alert>
          {error.isRetryable ? (
            <Button onClick={() => void refetch()} loading={isRefetching} variant="outline">
              Try again
            </Button>
          ) : null}
        </div>
      ) : null}

      {!isPending && !isError && courses.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <SearchX className="h-8 w-8 text-muted-foreground" aria-hidden="true" />
            <div>
              <p className="font-medium">No courses found</p>
              <p className="text-sm text-muted-foreground">
                {hasFilters
                  ? "Try a different search term or level."
                  : "Courses will appear here once they are published."}
              </p>
            </div>
            {hasFilters ? (
              <Button
                variant="outline"
                onClick={() => {
                  setSearchInput("");
                  setDebouncedSearch("");
                  setDifficulty("");
                }}
              >
                Clear filters
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {courses.length > 0 ? (
        <>
          {/* A list, not a bare grid of divs: assistive tech announces the count. */}
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {courses.map((course) => (
              <li key={course.id}>
                <CourseCard course={course} />
              </li>
            ))}
          </ul>

          {hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => void fetchNextPage()}
                loading={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading…" : "Load more"}
              </Button>
            </div>
          ) : (
            <p className="text-center text-sm text-muted-foreground">
              That is every course.
            </p>
          )}
        </>
      ) : null}
    </div>
  );
}

/** Placeholder grid matching the real layout, so the page does not jump. */
function CatalogueSkeleton() {
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3" aria-busy="true">
      {[0, 1, 2, 3, 4, 5].map((index) => (
        <li key={index}>
          <Card>
            <CardHeader className="space-y-3">
              <Skeleton className="h-5 w-24" />
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-full" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-4 w-32" />
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}
