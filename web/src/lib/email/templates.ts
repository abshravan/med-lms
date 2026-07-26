/**
 * Auth email bodies.
 *
 * Kept out of `auth/server.ts` so copy changes never risk touching auth
 * configuration, and so each template is independently testable.
 */

import type { EmailMessage } from "@/lib/email";

const PRODUCT_NAME = "MedLMS";

function signature(): string {
  return `\n\nThanks,\nThe ${PRODUCT_NAME} team`;
}

export function verificationEmail(params: {
  to: string;
  name: string | null;
  url: string;
}): EmailMessage {
  const greeting = params.name !== null ? `Hi ${params.name},` : "Hi,";
  return {
    to: params.to,
    subject: `Verify your ${PRODUCT_NAME} email address`,
    text:
      `${greeting}\n\n` +
      `Confirm your email address to activate your ${PRODUCT_NAME} account:\n\n` +
      `${params.url}\n\n` +
      `This link expires in 1 hour. If you did not create an account, ignore this email.` +
      signature(),
  };
}

export function passwordResetEmail(params: {
  to: string;
  name: string | null;
  url: string;
}): EmailMessage {
  const greeting = params.name !== null ? `Hi ${params.name},` : "Hi,";
  return {
    to: params.to,
    subject: `Reset your ${PRODUCT_NAME} password`,
    text:
      `${greeting}\n\n` +
      `Use this link to choose a new password:\n\n` +
      `${params.url}\n\n` +
      `The link expires in 1 hour and can only be used once. ` +
      `If you did not request a reset, you can safely ignore this email — ` +
      `your password has not changed.` +
      signature(),
  };
}
