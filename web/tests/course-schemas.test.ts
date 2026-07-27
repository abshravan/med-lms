/**
 * Course authoring validation and formatting tests.
 */

import { describe, expect, it } from "vitest";

import {
  courseFormSchema,
  lessonFormSchema,
  minutesToSeconds,
  moduleFormSchema,
  secondsToMinutes,
} from "@/features/courses/schemas";
import { formatDuration } from "@/features/courses/types";

describe("courseFormSchema", () => {
  it("accepts a minimal course", () => {
    const result = courseFormSchema.parse({ title: "Cardiology" });

    expect(result.title).toBe("Cardiology");
    expect(result.difficulty).toBe("foundation");
    // A blank optional field is omitted, not sent as "" — which the server rejects.
    expect(result.slug).toBeUndefined();
  });

  it("requires a title", () => {
    expect(courseFormSchema.safeParse({ title: "   " }).success).toBe(false);
  });

  it("treats a blank slug as absent so the server derives one", () => {
    const result = courseFormSchema.parse({ title: "Anatomy", slug: "" });
    expect(result.slug).toBeUndefined();
  });

  it.each([
    ["spaces", "not a slug"],
    ["uppercase", "NotASlug"],
    ["leading hyphen", "-anatomy"],
    ["double hyphen", "anatomy--basics"],
    ["trailing hyphen", "anatomy-"],
    ["punctuation", "anatomy!"],
  ])("rejects a malformed slug (%s)", (_label, slug) => {
    // Rejected rather than auto-corrected, matching the backend: a silently
    // rewritten slug makes the resulting URL a surprise.
    expect(courseFormSchema.safeParse({ title: "Anatomy", slug }).success).toBe(false);
  });

  it.each(["anatomy", "clinical-cardiology", "year-1-basics", "abc123"])(
    "accepts a valid slug (%s)",
    (slug) => {
      expect(courseFormSchema.safeParse({ title: "Anatomy", slug }).success).toBe(true);
    },
  );

  it("trims text fields", () => {
    const result = courseFormSchema.parse({
      title: "  Anatomy  ",
      specialty: "  Cardiology  ",
    });

    expect(result.title).toBe("Anatomy");
    expect(result.specialty).toBe("Cardiology");
  });

  it("has no status field, so publishing cannot be bypassed", () => {
    // Publishing runs server-side checks (at least one lesson); a status field
    // here would be a way around them.
    const result = courseFormSchema.parse({ title: "Anatomy", status: "published" });
    expect(result).not.toHaveProperty("status");
  });

  it("rejects an unknown difficulty", () => {
    expect(
      courseFormSchema.safeParse({ title: "Anatomy", difficulty: "impossible" }).success,
    ).toBe(false);
  });
});

describe("moduleFormSchema", () => {
  it("requires a title", () => {
    expect(moduleFormSchema.safeParse({ title: "" }).success).toBe(false);
    expect(moduleFormSchema.safeParse({ title: "Week 1" }).success).toBe(true);
  });
});

describe("lessonFormSchema", () => {
  it("defaults to a video lesson that is not a free preview", () => {
    const result = lessonFormSchema.parse({ title: "Intro" });

    expect(result.content_type).toBe("video");
    expect(result.is_free_preview).toBe(false);
  });

  it.each([0, -1, 86_401])("rejects an invalid duration (%s)", (duration) => {
    expect(
      lessonFormSchema.safeParse({ title: "Intro", duration_seconds: duration }).success,
    ).toBe(false);
  });

  it("rejects a fractional duration", () => {
    expect(
      lessonFormSchema.safeParse({ title: "Intro", duration_seconds: 90.5 }).success,
    ).toBe(false);
  });

  it("rejects an unknown content type", () => {
    expect(
      lessonFormSchema.safeParse({ title: "Intro", content_type: "hologram" }).success,
    ).toBe(false);
  });
});

describe("duration conversion", () => {
  it("converts author-entered minutes into API seconds", () => {
    expect(minutesToSeconds(10)).toBe(600);
    expect(minutesToSeconds(1.5)).toBe(90);
  });

  it("treats an absent or non-positive duration as unset", () => {
    expect(minutesToSeconds(undefined)).toBeUndefined();
    expect(minutesToSeconds(0)).toBeUndefined();
    expect(minutesToSeconds(-5)).toBeUndefined();
    expect(minutesToSeconds(Number.NaN)).toBeUndefined();
  });

  it("round-trips a whole-minute value", () => {
    expect(secondsToMinutes(minutesToSeconds(25) ?? null)).toBe(25);
  });

  it("treats a null duration as unset when populating a form", () => {
    expect(secondsToMinutes(null)).toBeUndefined();
    expect(secondsToMinutes(0)).toBeUndefined();
  });
});

describe("formatDuration", () => {
  it.each([
    [null, "—"],
    [0, "—"],
    [45, "45s"],
    [59, "59s"],
    [60, "1m"],
    [600, "10m"],
    // Rounds up into hours rather than reading as "60m".
    [3599, "1h"],
    [3600, "1h"],
    [3900, "1h 5m"],
    [7200, "2h"],
  ])("formats %s as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
