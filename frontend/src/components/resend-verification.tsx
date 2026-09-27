"use client";

import * as React from "react";

import { errorMessage } from "@/components/auth-provider";
import { Alert, Button } from "@/components/ui/primitives";
import { api } from "@/lib/api";

/**
 * "Send another verification email" button.
 *
 * Two endpoints do this, and which one applies depends on whether there is a
 * session:
 *
 * - signed in  -> `/auth/email/verify/send/`, which knows who is asking and
 *   reports honestly whether the provider accepted the message;
 * - signed out -> `/auth/resend-verification/`, which takes an address and
 *   answers the same way whatever the address is, so it cannot be used to work
 *   out who has an account.
 *
 * The second is why the success copy here is deliberately non-committal: this
 * component must not say "sent to you" when the backend would not confirm it.
 */
export function ResendVerification({
  email,
  authenticated = false,
  label = "Resend verification email",
}: {
  /** Required when signed out; ignored when authenticated. */
  email?: string;
  authenticated?: boolean;
  label?: string;
}) {
  const [state, setState] = React.useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = React.useState("");

  /**
   * Stops a second click landing while the first is still in flight. The
   * backend rate-limits this too - that is the control that matters - but
   * letting the button fire twice would spend the allowance on a double-send.
   */
  const inFlight = React.useRef(false);

  async function onClick() {
    if (inFlight.current) return;
    inFlight.current = true;
    setState("sending");
    setMessage("");

    try {
      if (authenticated) {
        await api.post("/auth/email/verify/send/", {});
      } else {
        if (!email) throw new Error("No email address to send to.");
        await api.post("/auth/resend-verification/", { email });
      }
      setState("sent");
    } catch (error) {
      setMessage(errorMessage(error));
      setState("error");
    } finally {
      inFlight.current = false;
    }
  }

  if (state === "sent") {
    return (
      <Alert tone="success" title="Verification email on its way">
        Check your inbox, and your spam folder if it is not there within a minute or two.
      </Alert>
    );
  }

  return (
    <div className="w-full">
      {state === "error" ? (
        <Alert tone="danger" title="Could not send that email" className="mb-3">
          {message}
        </Alert>
      ) : null}
      <Button
        type="button"
        variant="secondary"
        fullWidth
        size="lg"
        loading={state === "sending"}
        onClick={onClick}
      >
        {label}
      </Button>
    </div>
  );
}
