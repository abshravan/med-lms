/**
 * Registration form tests.
 *
 * The security-relevant assertion here is the absence of a role field: a public
 * sign-up form that lets the client pick a role is the classic
 * privilege-escalation bug in an LMS.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routerMock } from "../vitest.setup";

const signUpEmail = vi.fn();

vi.mock("@/lib/auth/client", () => ({
  authClient: {
    signUp: { email: (...args: unknown[]) => signUpEmail(...args) },
  },
}));

const { RegisterForm } = await import("@/features/auth/components/register-form");

const VALID_PASSWORD = "correct-horse-battery";

async function fillValidForm(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  await user.type(screen.getByLabelText("Full name"), "Ada Lovelace");
  await user.type(screen.getByLabelText("Email address"), "ada@med.test");
  await user.type(screen.getByLabelText("Password"), VALID_PASSWORD);
  await user.type(screen.getByLabelText("Confirm password"), VALID_PASSWORD);
  await user.click(screen.getByLabelText(/I agree to the/));
}

beforeEach(() => {
  signUpEmail.mockReset();
});

describe("RegisterForm", () => {
  it("exposes no role selector", () => {
    render(<RegisterForm />);

    // Role is assigned server-side and marked `input: false` in the Better Auth
    // config. If a role control ever appears here, that is a security regression.
    expect(screen.queryByLabelText(/role/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/administrator/i)).not.toBeInTheDocument();
  });

  it("requires every field", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Enter your full name")).toBeInTheDocument();
    expect(screen.getByText("Email address is required")).toBeInTheDocument();
    expect(
      screen.getByText("You must accept the terms to continue"),
    ).toBeInTheDocument();
    expect(signUpEmail).not.toHaveBeenCalled();
  });

  it("rejects a password below the minimum length", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await user.type(screen.getByLabelText("Password"), "short1!");
    await user.tab();

    expect(await screen.findByText(/at least 12 characters/i)).toBeInTheDocument();
  });

  it("reports mismatched passwords on the confirmation field", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await user.type(screen.getByLabelText("Password"), VALID_PASSWORD);
    await user.type(screen.getByLabelText("Confirm password"), "different-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Passwords do not match")).toBeInTheDocument();
  });

  it("shows a live strength indicator", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    await user.type(screen.getByLabelText("Password"), "abc");
    expect(await screen.findByText(/Password strength:/)).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "Th1s-Is-A-Long-Passphrase!");
    await waitFor(() =>
      expect(screen.getByText("Password strength: Strong")).toBeInTheDocument(),
    );
  });

  it("submits and routes to the verification notice", async () => {
    const user = userEvent.setup();
    signUpEmail.mockResolvedValue({ error: null });
    render(<RegisterForm />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => {
      expect(signUpEmail).toHaveBeenCalledWith({
        name: "Ada Lovelace",
        email: "ada@med.test",
        password: VALID_PASSWORD,
        callbackURL: "/dashboard",
      });
    });

    expect(routerMock.push).toHaveBeenCalledWith("/verify-email?sent=1");
  });

  it("never sends a role even if one were injected into the payload", async () => {
    const user = userEvent.setup();
    signUpEmail.mockResolvedValue({ error: null });
    render(<RegisterForm />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(signUpEmail).toHaveBeenCalled());
    expect(signUpEmail.mock.calls[0]![0]).not.toHaveProperty("role");
  });

  it("does not confirm whether an email is already registered", async () => {
    const user = userEvent.setup();
    signUpEmail.mockResolvedValue({
      error: { status: 422, message: "User already exists" },
    });
    render(<RegisterForm />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Create account" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("If you already have one, try signing in");
    expect(alert).not.toHaveTextContent("User already exists");
  });

  it("toggles password visibility without losing the value", async () => {
    const user = userEvent.setup();
    render(<RegisterForm />);

    const password = screen.getByLabelText("Password");
    await user.type(password, VALID_PASSWORD);
    expect(password).toHaveAttribute("type", "password");

    // The toggle names its own field, so the two on this form are distinguishable.
    await user.click(screen.getByRole("button", { name: "Show password" }));

    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Password")).toHaveValue(VALID_PASSWORD);
    // The confirmation field is unaffected.
    expect(screen.getByLabelText("Confirm password")).toHaveAttribute(
      "type",
      "password",
    );
  });

  it("gives each password toggle a distinct accessible name", () => {
    render(<RegisterForm />);

    expect(
      screen.getByRole("button", { name: "Show password" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Show confirm password" }),
    ).toBeInTheDocument();
  });
});
