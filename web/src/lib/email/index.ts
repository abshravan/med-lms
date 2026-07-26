/**
 * Transactional email.
 *
 * Authentication cannot ship without email — verification links and password
 * resets are part of the flow, not an enhancement. This module is deliberately
 * thin and provider-agnostic:
 *
 * - `ConsoleTransport` (default in development) logs the message and the link, so
 *   the whole flow is testable with no third-party account and no risk of mailing
 *   a real person from a dev machine.
 * - `ResendTransport` is used when `RESEND_API_KEY` is present.
 *
 * The `EmailTransport` interface is the seam. Swapping Resend for SES or Postmark
 * is a new implementation of one small interface, not a change to auth code.
 * Resend is chosen as the default provider because it needs no SDK — a single
 * `fetch` call — which keeps the dependency graph smaller than the alternatives.
 *
 * Sending is intentionally synchronous with the request for now. Once the ARQ
 * worker exists (see docs/architecture.md §9), this should enqueue instead, so a
 * slow provider cannot slow down sign-up. Noted as technical debt.
 */

import { getServerEnv } from "@/lib/env";

export interface EmailMessage {
  to: string;
  subject: string;
  /** Plain-text body. Deliverability is better with text than HTML-only. */
  text: string;
  html?: string;
}

export interface EmailTransport {
  readonly name: string;
  send(message: EmailMessage): Promise<void>;
}

class ConsoleTransport implements EmailTransport {
  readonly name = "console";

  async send(message: EmailMessage): Promise<void> {
    // Deliberately verbose: in development this output *is* the inbox.
    console.info(
      [
        "",
        "──────────── outbound email (console transport) ────────────",
        `to:      ${message.to}`,
        `subject: ${message.subject}`,
        "",
        message.text,
        "────────────────────────────────────────────────────────────",
        "",
      ].join("\n"),
    );
  }
}

class ResendTransport implements EmailTransport {
  readonly name = "resend";

  constructor(
    private readonly apiKey: string,
    private readonly from: string,
  ) {}

  async send(message: EmailMessage): Promise<void> {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: this.from,
        to: [message.to],
        subject: message.subject,
        text: message.text,
        ...(message.html !== undefined ? { html: message.html } : {}),
      }),
    });

    if (!response.ok) {
      // The recipient address is not logged — it is personal data, and the
      // provider's response is enough to diagnose a delivery failure.
      const detail = await response.text().catch(() => "");
      throw new Error(
        `Resend rejected the message (${response.status}): ${detail.slice(0, 200)}`,
      );
    }
  }
}

let transport: EmailTransport | null = null;

/** The configured transport for this process. */
export function getEmailTransport(): EmailTransport {
  if (transport !== null) {
    return transport;
  }

  const env = getServerEnv();
  transport =
    env.RESEND_API_KEY !== undefined && env.RESEND_API_KEY.length > 0
      ? new ResendTransport(env.RESEND_API_KEY, env.EMAIL_FROM)
      : new ConsoleTransport();

  return transport;
}

/** Override the transport. Used by tests. */
export function setEmailTransport(next: EmailTransport | null): void {
  transport = next;
}

/**
 * Send an email, converting a provider failure into a logged warning.
 *
 * Auth flows call this. A failed verification email must not turn a successful
 * registration into a 500 — the account exists, and the user can request another
 * link. The failure is logged loudly for operators.
 */
export async function sendEmailSafely(message: EmailMessage): Promise<boolean> {
  try {
    await getEmailTransport().send(message);
    return true;
  } catch (error) {
    console.error(
      "[email] delivery failed",
      error instanceof Error ? error.message : String(error),
    );
    return false;
  }
}
