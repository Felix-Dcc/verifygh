"use client";

import QRCode from "qrcode";
import * as React from "react";

import { errorMessage, useAuth } from "@/components/auth-provider";
import { Dialog } from "@/components/ui/dialog";
import { Alert, Badge, Button, Field, Input, PasswordInput } from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";

type Setup = { secret: string; otpauth_uri: string };

/**
 * Two-factor sign-in: set up with an authenticator app, save the recovery
 * codes, and later turn it off or renew the codes. Used on the account page
 * and, for staff who have not set it up, in place of the admin console.
 */
export function TwoFactorSettings() {
  const { user, refresh } = useAuth();
  const toast = useToast();
  const [setup, setSetup] = React.useState<Setup | null>(null);
  const [qr, setQr] = React.useState("");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [recoveryCodes, setRecoveryCodes] = React.useState<string[] | null>(null);
  const [confirming, setConfirming] = React.useState<"disable" | "renew" | null>(null);

  React.useEffect(() => {
    if (!setup) return;
    // Drawn here, to a data: URL: the secret never leaves the browser for a
    // QR service, and the page's CSP already allows data: images.
    QRCode.toDataURL(setup.otpauth_uri, { margin: 1, width: 192 })
      .then(setQr)
      .catch(() => setQr(""));
  }, [setup]);

  if (!user) return null;

  async function start() {
    setBusy(true);
    setError("");
    try {
      setSetup(await api.post<Setup>("/auth/2fa/setup/", {}));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await api.post<{ recovery_codes: string[] }>("/auth/2fa/enable/", { code });
      setRecoveryCodes(response.recovery_codes);
      setSetup(null);
      setCode("");
      // The account is refreshed only once the codes are saved (below): the
      // admin gate swaps this screen for the console the moment it sees
      // two-factor on, which hid the codes before anyone could save them.
      toast.success("Two-factor sign-in is on");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (recoveryCodes) {
    return (
      <RecoveryCodes
        codes={recoveryCodes}
        onDone={async () => {
          setRecoveryCodes(null);
          await refresh();
        }}
      />
    );
  }

  if (user.is_two_factor_enabled) {
    return (
      <div className="space-y-4 p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="success">On</Badge>
          <span className="text-sm text-ink-muted">
            Signing in asks for a code from your authenticator app.{" "}
            {user.two_factor_recovery_codes_left} recovery{" "}
            {user.two_factor_recovery_codes_left === 1 ? "code" : "codes"} left.
          </span>
        </div>
        {user.two_factor_recovery_codes_left <= 2 ? (
          <Alert tone="warn" title="Running out of recovery codes">
            Make a new set so you can still sign in if you lose your phone.
          </Alert>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setConfirming("renew")}>
            New recovery codes
          </Button>
          <Button variant="ghost" onClick={() => setConfirming("disable")}>
            Turn off
          </Button>
        </div>
        <ConfirmIdentity
          mode={confirming}
          hasPassword={user.has_password !== false}
          onClose={() => setConfirming(null)}
          onDone={async (codes) => {
            setConfirming(null);
            if (codes) setRecoveryCodes(codes);
            await refresh();
          }}
        />
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5 sm:p-6">
      {user.two_factor_required ? (
        <Alert tone="info" title="Required for staff">
          Staff accounts can change balances and prices, so the admin console needs a code from
          your phone as well as your password.
        </Alert>
      ) : null}
      {error ? <Alert tone="danger">{error}</Alert> : null}

      {!setup ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-sm text-ink-muted">
            Add a code from an authenticator app (Google Authenticator, Microsoft Authenticator,
            1Password and others) to every sign-in.
          </p>
          <Button onClick={start} loading={busy} className="shrink-0">
            Set up
          </Button>
        </div>
      ) : (
        <form onSubmit={confirm} className="space-y-4">
          <ol className="list-decimal space-y-3 pl-5 text-sm text-ink-soft">
            <li>Open your authenticator app and add an account.</li>
            <li>
              Scan this code, or type the key instead.
              <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-center">
                {qr ? (
                  // eslint-disable-next-line @next/next/no-img-element -- a data: URL drawn locally
                  <img
                    src={qr}
                    alt="QR code for your authenticator app"
                    width={160}
                    height={160}
                    className="rounded-lg border border-line bg-white p-1"
                  />
                ) : null}
                <code className="break-all rounded-lg bg-sunken px-3 py-2 font-mono text-sm text-ink">
                  {setup.secret.replace(/(.{4})/g, "$1 ").trim()}
                </code>
              </div>
            </li>
            <li>Enter the 6-digit code it shows.</li>
          </ol>
          <Field label="Code from the app" htmlFor="two-factor-setup-code" required>
            <Input
              id="two-factor-setup-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
              className="font-mono tracking-[0.3em]"
            />
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" type="button" onClick={() => setSetup(null)}>
              Cancel
            </Button>
            <Button type="submit" loading={busy} disabled={code.length !== 6}>
              Turn on
            </Button>
          </div>
        </form>
      )}
    </div>
  );
}

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const toast = useToast();
  async function copy() {
    try {
      await navigator.clipboard.writeText(codes.join("\n"));
      toast.success("Recovery codes copied");
    } catch {
      toast.error("Could not copy", "Select the codes and copy them by hand.");
    }
  }
  return (
    <div className="space-y-4 p-5 sm:p-6">
      <Alert tone="warn" title="Save these recovery codes now">
        Each one signs you in once if you lose your phone. They will not be shown again - keep
        them in a password manager or somewhere safe.
      </Alert>
      <ul className="grid grid-cols-2 gap-2 font-mono text-sm text-ink sm:grid-cols-5">
        {codes.map((value) => (
          <li key={value} className="rounded-lg bg-sunken px-2.5 py-1.5 text-center">
            {value}
          </li>
        ))}
      </ul>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={copy}>
          Copy
        </Button>
        <Button onClick={onDone}>I have saved them</Button>
      </div>
    </div>
  );
}

function ConfirmIdentity({
  mode,
  hasPassword,
  onClose,
  onDone,
}: {
  mode: "disable" | "renew" | null;
  hasPassword: boolean;
  onClose: () => void;
  onDone: (codes?: string[]) => void;
}) {
  const toast = useToast();
  const [password, setPassword] = React.useState("");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (mode) {
      setPassword("");
      setCode("");
      setError("");
    }
  }, [mode]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (mode === "disable") {
        await api.post("/auth/2fa/disable/", { password, code });
        toast.success("Two-factor sign-in is off");
        onDone();
      } else {
        const response = await api.post<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes/", {
          password,
          code,
        });
        onDone(response.recovery_codes);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={mode !== null}
      onClose={onClose}
      title={mode === "disable" ? "Turn off two-factor sign-in?" : "Make new recovery codes?"}
      description={
        mode === "disable"
          ? "Signing in will need only your password. Staff will need to set it up again to use the admin console."
          : "Your current recovery codes will stop working."
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={!code || (hasPassword && !password)}>
            {mode === "disable" ? "Turn off" : "Make new codes"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {error ? <Alert tone="danger">{error}</Alert> : null}
        {hasPassword ? (
          <Field label="Password" htmlFor="two-factor-confirm-password" required>
            <PasswordInput
              id="two-factor-confirm-password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
        ) : null}
        <Field label="Code from your app, or a recovery code" htmlFor="two-factor-confirm-code" required>
          <Input
            id="two-factor-confirm-code"
            autoComplete="one-time-code"
            value={code}
            onChange={(event) => setCode(event.target.value)}
            className="font-mono"
          />
        </Field>
      </div>
    </Dialog>
  );
}
