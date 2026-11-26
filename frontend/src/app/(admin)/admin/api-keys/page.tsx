"use client";

import * as React from "react";
import useSWR from "swr";

import { ListCard } from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { useAuth } from "@/components/auth-provider";
import { CheckIcon, CopyIcon, LockIcon, PlusIcon } from "@/components/icons";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Field,
  Input,
  LoadError,
  Select,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { formatDate, relativeTime } from "@/lib/format";

/**
 * Admin > API keys: your own keys, for handing to a program or an assistant
 * when you can't share a browser session. A key acts as you on the admin API
 * only, with your current role, until it expires or you revoke it.
 */

type KeyStatus = "ACTIVE" | "REVOKED" | "EXPIRED" | "SIGNED_OUT";

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  display: string;
  access: "READ" | "WRITE";
  status: KeyStatus;
  expires_at: string;
  last_used_at: string | null;
  last_used_ip: string | null;
  revoked_at: string | null;
  created_at: string;
}

const STATUS: Record<KeyStatus, { label: string; tone: "success" | "neutral" | "warn" }> = {
  ACTIVE: { label: "Active", tone: "success" },
  REVOKED: { label: "Revoked", tone: "neutral" },
  EXPIRED: { label: "Expired", tone: "neutral" },
  SIGNED_OUT: { label: "Ended by sign-out", tone: "warn" },
};

export default function AdminApiKeysPage() {
  const { user } = useAuth();
  const toast = useToast();
  const { data, error, isValidating, mutate } = useSWR<ApiKey[]>("/admin/api-keys/");
  const [creating, setCreating] = React.useState(false);
  const [created, setCreated] = React.useState<(ApiKey & { key: string }) | null>(null);
  const [revoking, setRevoking] = React.useState<ApiKey | null>(null);
  const [busy, setBusy] = React.useState(false);

  async function revoke() {
    if (!revoking) return;
    setBusy(true);
    try {
      await api.post(`/admin/api-keys/${revoking.id}/revoke/`, {});
      toast.success("Key revoked", "It stopped working immediately.");
      setRevoking(null);
      await mutate();
    } catch (caught) {
      toast.error("Could not revoke", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  const keys = data ?? [];
  const noTwoFactor = user && !user.is_two_factor_enabled;

  return (
    <div className="space-y-6">
      <PageHeader
        title="API keys"
        description="Let a program or assistant use the admin console as you, without your password."
        action={
          <Button icon={<PlusIcon />} onClick={() => setCreating(true)} disabled={Boolean(noTwoFactor)}>
            New key
          </Button>
        }
      />

      <Alert tone="info" title="What a key can do">
        A key acts as you, with your current role, on the admin console only. It cannot place orders,
        touch your own wallet or create other keys. It stops working when it expires, when you revoke
        it, when you sign out everywhere or change your password, or if your role is removed.
        Everything done with a key is marked as such in the audit log.
      </Alert>

      {noTwoFactor ? (
        <Alert tone="warn" title="Two-factor sign-in needed">
          Turn on two-factor sign-in on your <a href="/account" className="underline">account page</a>{" "}
          before creating a key.
        </Alert>
      ) : null}

      <ListCard
        title="Your keys"
        count={keys.length}
        noun="keys"
        refreshing={isValidating}
        onRefresh={() => mutate()}
      >
        {error && !data ? (
          <LoadError what="your keys" onRetry={() => mutate()} />
        ) : !data ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : keys.length === 0 ? (
          <EmptyState icon={<LockIcon />} title="No keys yet" description="Keys you create appear here." />
        ) : (
          <ul className="divide-y divide-line">
            {keys.map((key) => (
              <li key={key.id} className="px-4 py-4 sm:px-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-ink">{key.name}</span>
                      <Badge tone={STATUS[key.status].tone}>{STATUS[key.status].label}</Badge>
                      <Badge tone={key.access === "WRITE" ? "warn" : "info"}>
                        {key.access === "WRITE" ? "Read and act" : "Read only"}
                      </Badge>
                    </div>
                    <p className="mt-1 break-all font-mono text-caption text-ink-soft">{key.display}</p>
                    <p className="mt-1 text-caption text-ink-muted">
                      Created {formatDate(key.created_at)}
                      <span className="mx-1.5" aria-hidden>&middot;</span>
                      {key.status === "ACTIVE" ? `Expires ${formatDate(key.expires_at)}` : null}
                      {key.status === "REVOKED" ? `Revoked ${formatDate(key.revoked_at)}` : null}
                      {key.status === "EXPIRED" ? `Expired ${formatDate(key.expires_at)}` : null}
                      {key.status === "SIGNED_OUT" ? "Ended when you signed out everywhere" : null}
                      <span className="mx-1.5" aria-hidden>&middot;</span>
                      {key.last_used_at ? `Last used ${relativeTime(key.last_used_at)}` : "Never used"}
                    </p>
                  </div>
                  {key.status === "ACTIVE" ? (
                    <Button size="sm" variant="secondary" onClick={() => setRevoking(key)}>
                      Revoke
                    </Button>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </ListCard>

      <CreateKeyDialog
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={(key) => {
          setCreating(false);
          setCreated(key);
          mutate();
        }}
      />

      <Dialog
        open={Boolean(created)}
        onClose={() => setCreated(null)}
        title="Copy your key now"
        description="This is the only time it is shown. Store it somewhere safe or paste it where it's needed."
      >
        {created ? <ShowKey raw={created.key} /> : null}
      </Dialog>

      <Dialog
        open={Boolean(revoking)}
        onClose={() => setRevoking(null)}
        title="Revoke this key?"
        description={revoking ? `"${revoking.name}" stops working immediately. This can't be undone.` : undefined}
        dismissible={!busy}
        footer={
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button variant="secondary" onClick={() => setRevoking(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" onClick={revoke} loading={busy}>
              Revoke
            </Button>
          </div>
        }
      />
    </div>
  );
}

function CreateKeyDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (key: ApiKey & { key: string }) => void;
}) {
  const toast = useToast();
  const [name, setName] = React.useState("");
  const [access, setAccess] = React.useState<"READ" | "WRITE">("READ");
  const [days, setDays] = React.useState("7");
  const [code, setCode] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setName("");
      setAccess("READ");
      setDays("7");
      setCode("");
    }
  }, [open]);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    setBusy(true);
    try {
      const key = await api.post<ApiKey & { key: string }>("/admin/api-keys/", {
        name: name.trim(),
        access,
        days: Number(days),
        code: code.trim(),
      });
      onCreated(key);
    } catch (caught) {
      toast.error("Could not create the key", caught instanceof ApiError ? caught.message : "Try again.");
    } finally {
      setBusy(false);
    }
  }

  const ready = name.trim().length >= 2 && code.trim().length >= 6;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New API key"
      dismissible={!busy}
      footer={
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => submit()} loading={busy} disabled={!ready}>
            Create key
          </Button>
        </div>
      }
    >
      <form className="space-y-4" onSubmit={submit}>
        <Field label="Name" htmlFor="key-name" required hint="So you can tell keys apart, e.g. Claude assistant.">
          <Input id="key-name" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field
          label="Access"
          htmlFor="key-access"
          hint={
            access === "WRITE"
              ? "Can do anything your role can in the console, such as resolving signals or suspending users."
              : "Can look at anything your role can see, but change nothing."
          }
        >
          <Select id="key-access" value={access} onChange={(event) => setAccess(event.target.value as "READ" | "WRITE")}>
            <option value="READ">Read only</option>
            <option value="WRITE">Read and act</option>
          </Select>
        </Field>
        <Field label="Expires after" htmlFor="key-days">
          <Select id="key-days" value={days} onChange={(event) => setDays(event.target.value)}>
            <option value="1">1 day</option>
            <option value="7">7 days</option>
            <option value="30">30 days</option>
            <option value="90">90 days</option>
          </Select>
        </Field>
        <Field label="Two-factor code" htmlFor="key-code" required hint="From your authenticator app, or a recovery code.">
          <Input
            id="key-code"
            value={code}
            autoComplete="one-time-code"
            inputMode="text"
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
      </form>
    </Dialog>
  );
}

function ShowKey({ raw }: { raw: string }) {
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(raw);
    } catch {
      const field = document.createElement("textarea");
      field.value = raw;
      field.setAttribute("readonly", "");
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      try {
        document.execCommand("copy");
      } finally {
        document.body.removeChild(field);
      }
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="space-y-3">
      <p className="select-all break-all rounded-lg bg-sunken px-3 py-3 font-mono text-sm text-ink">{raw}</p>
      <Button fullWidth icon={copied ? <CheckIcon /> : <CopyIcon />} onClick={copy}>
        {copied ? "Copied" : "Copy key"}
      </Button>
    </div>
  );
}
