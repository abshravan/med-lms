/**
 * Login form behaviour tests.
 *
 * Written from the user's point of view — queried by label and role, not by CSS
 * class — so the tests survive restyling and would catch an accessibility
 * regression (a missing label, an unannounced error) rather than ignoring it.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { routerMock } from "../vitest.setup";

const signInEmail = vi.fn();

vi.mock("@/lib/auth/client", () => ({
  authClient: {
    signIn: { email: (...args: unknown[]) => signInEmail(...args) },
  },
}));

vi.mock("@/lib/api/client", () => ({
  clearCachedAccessToken: vi.fn(),
}));

const { LoginForm } = await import("@/features/auth/components/login-form");

beforeEach(() => {
  signInEmail.mockReset();
});

describe("LoginForm", () => {
  it("renders labelled, correctly-typed fields", () => {
    render(<LoginForm />);

    const email = screen.getByLabelText("Email address");
    expect(email).toHaveAttribute("type", "email");
    // `current-password` lets password managers fill correctly.
    expect(screen.getByLabelText("Password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows validation messages and does not call the API", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Email address is required")).toBeInTheDocument();
    expect(await screen.findByText("Password is required")).toBeInTheDocument();
    expect(signInEmail).not.toHaveBeenCalled();
  });

  it("rejects a malformed email before submitting", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email address"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(signInEmail).not.toHaveBeenCalled();
  });

  it("submits normalised credentials and redirects on success", async () => {
    const user = userEvent.setup();
    signInEmail.mockResolvedValue({ error: null });
    render(<LoginForm redirectTo="/courses/anatomy" />);

    await user.type(screen.getByLabelText("Email address"), "  Ada@Med.TEST ");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(signInEmail).toHaveBeenCalledWith({
        // Trimmed and lower-cased by the schema before it reaches the client.
        email: "ada@med.test",
        password: "correct-horse-battery",
        rememberMe: true,
      });
    });

    expect(routerMock.replace).toHaveBeenCalledWith("/courses/anatomy");
  });

  it("reports a generic message on bad credentials, avoiding account enumeration", async () => {
    const user = userEvent.setup();
    signInEmail.mockResolvedValue({ error: { status: 401, message: "User not found" } });
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email address"), "ada@med.test");
    await user.type(screen.getByLabelText("Password"), "wrong-password-here");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "That email address and password do not match an account.",
    );
    // The upstream "User not found" must never reach the user — it would confirm
    // which addresses are registered.
    expect(alert).not.toHaveTextContent("User not found");
    expect(routerMock.replace).not.toHaveBeenCalled();
  });

  it("reports a suspended account distinctly", async () => {
    const user = userEvent.setup();
    signInEmail.mockResolvedValue({ error: { status: 403, message: "banned" } });
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email address"), "ada@med.test");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This account has been suspended",
    );
  });

  it("disables the submit button while in flight to prevent double submission", async () => {
    const user = userEvent.setup();
    let release: (value: { error: null }) => void = () => {};
    signInEmail.mockReturnValue(
      new Promise<{ error: null }>((resolve) => {
        release = resolve;
      }),
    );
    render(<LoginForm />);

    await user.type(screen.getByLabelText("Email address"), "ada@med.test");
    await user.type(screen.getByLabelText("Password"), "correct-horse-battery");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const button = await screen.findByRole("button", { name: /Signing in/ });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");

    release({ error: null });
    await waitFor(() => expect(signInEmail).toHaveBeenCalledTimes(1));
  });

  it("marks an invalid field for assistive technology", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const email = screen.getByLabelText("Email address");
    await waitFor(() => expect(email).toHaveAttribute("aria-invalid", "true"));
    // The message is linked to the input, not merely rendered beside it.
    expect(email).toHaveAttribute("aria-describedby", "email-error");
  });

  it("offers password recovery and registration paths", () => {
    render(<LoginForm />);

    expect(screen.getByRole("link", { name: "Forgot password?" })).toHaveAttribute(
      "href",
      "/forgot-password",
    );
    expect(screen.getByRole("link", { name: "Create an account" })).toHaveAttribute(
      "href",
      "/register",
    );
  });
});
