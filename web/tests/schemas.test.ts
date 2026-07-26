/**
 * Validation-schema tests.
 *
 * These schemas are the client-side contract for every auth form, so each rule
 * that could reject a legitimate user — or admit a bad value — is pinned here.
 */

import { describe, expect, it } from "vitest";

import {
  PASSWORD_MIN_LENGTH,
  estimatePasswordStrength,
  forgotPasswordSchema,
  profileUpdateSchema,
  resetPasswordSchema,
  signInSchema,
  signUpSchema,
} from "@/features/auth/schemas";

describe("emailSchema (via signInSchema)", () => {
  it("normalises case and surrounding whitespace", () => {
    const result = signInSchema.parse({
      email: "  Ada@Med.TEST  ",
      password: "whatever",
      rememberMe: true,
    });

    // Without normalisation, `Ada@Med.test` and `ada@med.test` become two accounts.
    expect(result.email).toBe("ada@med.test");
  });

  it.each([
    ["missing @", "ada.med.test"],
    ["no domain", "ada@"],
    ["empty", ""],
    ["spaces inside", "ada lovelace@med.test"],
  ])("rejects an invalid address (%s)", (_label, email) => {
    const result = signInSchema.safeParse({ email, password: "x", rememberMe: true });
    expect(result.success).toBe(false);
  });

  it("rejects an address beyond the RFC maximum length", () => {
    const result = forgotPasswordSchema.safeParse({
      email: `${"a".repeat(320)}@med.test`,
    });
    expect(result.success).toBe(false);
  });
});

describe("signInSchema", () => {
  it("does not enforce the password policy at sign-in", () => {
    // An account created before a policy change must still be able to sign in.
    const result = signInSchema.safeParse({
      email: "ada@med.test",
      password: "short",
      rememberMe: false,
    });
    expect(result.success).toBe(true);
  });

  it("requires a non-empty password", () => {
    const result = signInSchema.safeParse({
      email: "ada@med.test",
      password: "",
      rememberMe: false,
    });
    expect(result.success).toBe(false);
  });
});

describe("signUpSchema", () => {
  const valid = {
    name: "Ada Lovelace",
    email: "ada@med.test",
    password: "correct-horse-battery",
    confirmPassword: "correct-horse-battery",
    acceptedTerms: true,
  };

  it("accepts a well-formed registration", () => {
    expect(signUpSchema.safeParse(valid).success).toBe(true);
  });

  it(`rejects a password shorter than ${PASSWORD_MIN_LENGTH} characters`, () => {
    const result = signUpSchema.safeParse({
      ...valid,
      password: "short1!",
      confirmPassword: "short1!",
    });
    expect(result.success).toBe(false);
  });

  it("accepts a long passphrase with no symbols or digits", () => {
    // Length is the property that resists cracking; composition rules are not
    // enforced on purpose.
    const result = signUpSchema.safeParse({
      ...valid,
      password: "several plain english words here",
      confirmPassword: "several plain english words here",
    });
    expect(result.success).toBe(true);
  });

  it("rejects a common password that clears the length rule", () => {
    const result = signUpSchema.safeParse({
      ...valid,
      password: "passwordpassword",
      confirmPassword: "passwordpassword",
    });
    expect(result.success).toBe(false);
  });

  it("reports a password mismatch on the confirm field", () => {
    const result = signUpSchema.safeParse({
      ...valid,
      confirmPassword: "correct-horse-batterz",
    });

    expect(result.success).toBe(false);
    if (!result.success) {
      // Attached to the field the user must fix, not to the form root.
      expect(result.error.issues[0]?.path).toEqual(["confirmPassword"]);
    }
  });

  it("requires the terms checkbox", () => {
    const result = signUpSchema.safeParse({ ...valid, acceptedTerms: false });
    expect(result.success).toBe(false);
  });

  it("has no role field, so a role cannot be submitted", () => {
    // Privilege escalation via mass assignment: the parsed output must not carry
    // a role even when one is supplied.
    const result = signUpSchema.parse({ ...valid, role: "admin" });
    expect(result).not.toHaveProperty("role");
  });
});

describe("resetPasswordSchema", () => {
  it("enforces the full password policy", () => {
    const result = resetPasswordSchema.safeParse({
      password: "short",
      confirmPassword: "short",
    });
    expect(result.success).toBe(false);
  });

  it("requires both entries to match", () => {
    const result = resetPasswordSchema.safeParse({
      password: "a-perfectly-fine-passphrase",
      confirmPassword: "a-perfectly-fine-passphrasf",
    });
    expect(result.success).toBe(false);
  });
});

describe("profileUpdateSchema", () => {
  it("accepts an empty object, making PATCH idempotent", () => {
    expect(profileUpdateSchema.safeParse({}).success).toBe(true);
  });

  it("trims string fields", () => {
    const result = profileUpdateSchema.parse({ institution: "  AIIMS  " });
    expect(result.institution).toBe("AIIMS");
  });

  it.each([0, 11, 1.5])("rejects an out-of-range year (%s)", (year) => {
    expect(profileUpdateSchema.safeParse({ year_of_study: year }).success).toBe(false);
  });

  it.each([1, 5, 10])("accepts a valid year (%s)", (year) => {
    expect(profileUpdateSchema.safeParse({ year_of_study: year }).success).toBe(true);
  });
});

describe("estimatePasswordStrength", () => {
  it("returns an empty label for an empty password", () => {
    expect(estimatePasswordStrength("")).toEqual({ score: 0, label: "" });
  });

  it("scores a short password lower than a long, mixed one", () => {
    const weak = estimatePasswordStrength("abcdefgh");
    const strong = estimatePasswordStrength("Th1s-Is-A-Long-Passphrase!");
    expect(strong.score).toBeGreaterThan(weak.score);
  });

  it("never exceeds the maximum score", () => {
    const result = estimatePasswordStrength("Aa1!".repeat(20));
    expect(result.score).toBeLessThanOrEqual(4);
    expect(result.label).toBe("Strong");
  });
});
