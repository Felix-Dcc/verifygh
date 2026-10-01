"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { PageHeader } from "@/components/app-shell";
import { CheckCircleIcon, SearchIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadError,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";

type QueueRow = { slug: string; name: string; category: string; is_popular: boolean };
type Queue = { configured: boolean; count: number; page: number; pages: number; results: QueueRow[] };
type Candidate = { name: string; domain: string; claimed: boolean; logo_url: string };

/** "Wells Fargo" and "wellsfargo" are the same name; "Wells" is not. */
function sameName(a: string, b: string) {
  const key = (text: string) => text.toLowerCase().replace(/&/g, "and").replace(/[^a-z0-9]/g, "");
  return key(a) === key(b);
}

/**
 * Admin > Logos: match each service with no logo to its brand's official one.
 *
 * For every service on sale that still shows the generic tile, the API asks
 * Brandfetch - live - which brands carry that name, and shows each with its
 * logo. Staff pick the right company, or say none of them is. Nothing is
 * matched automatically: many names belong to more than one company, and a
 * missing logo is better than someone else's.
 */
export default function AdminLogosPage() {
  const [search, setSearch] = React.useState("");
  const [debounced, setDebounced] = React.useState("");
  const [page, setPage] = React.useState(1);

  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const { data, error, isLoading, mutate } = useSWR<Queue>([
    "/admin/services/logo-queue/",
    { page, search: debounced },
  ]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Logos"
        description="Match services to their brand's official logo. Logos come from Brandfetch, as each brand publishes them."
      />

      {data && !data.configured ? (
        <Alert tone="warn" title="Brandfetch is not set up">
          Create a free account at developers.brandfetch.com, copy your client ID, and set
          BRANDFETCH_CLIENT_ID on the API service in Railway. This page then finds logos.
        </Alert>
      ) : null}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm text-ink-muted">
          {data
            ? data.count === 1
              ? "1 service on sale still shows the generic tile."
              : `${data.count} services on sale still show the generic tile.`
            : " "}
        </p>
        <div className="relative sm:w-80">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Find a service"
            className="pl-9"
            aria-label="Find a service"
          />
        </div>
      </div>

      {error && !data ? (
        <Card>
          <LoadError what="the logo queue" onRetry={() => mutate()} />
        </Card>
      ) : isLoading || !data ? (
        <Card className="space-y-2 p-4">
          {[0, 1, 2, 3].map((row) => (
            <Skeleton key={row} className="h-20 w-full" />
          ))}
        </Card>
      ) : data.results.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CheckCircleIcon />}
            title={debounced ? "No service matches that search" : "Every service on sale has been decided"}
            description="Services the catalogue sync adds later appear here when they go on sale."
          />
        </Card>
      ) : (
        <Card className="divide-y divide-line overflow-hidden">
          {data.results.map((row) => (
            <QueueItem key={row.slug} row={row} enabled={data.configured} onDone={() => mutate()} />
          ))}
        </Card>
      )}

      {data ? (
        <Pagination
          page={data.page}
          pages={data.pages}
          count={data.count}
          hasNext={data.page < data.pages}
          hasPrevious={data.page > 1}
          onChange={(update) => setPage(update)}
          noun="services"
        />
      ) : null}
    </div>
  );
}

function QueueItem({ row, enabled, onDone }: { row: QueueRow; enabled: boolean; onDone: () => void }) {
  const toast = useToast();
  const [query, setQuery] = React.useState(row.name);
  const [draft, setDraft] = React.useState(row.name);
  const [website, setWebsite] = React.useState("");
  const [busy, setBusy] = React.useState("");

  const { data, error, isLoading, mutate } = useSWR<{ query: string; results: Candidate[] }>(
    enabled ? [`/admin/services/${row.slug}/logo-candidates/`, { q: query }] : null,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  async function decide(body: Record<string, unknown>, done: string, key: string) {
    setBusy(key);
    try {
      await api.post(`/admin/services/${row.slug}/brand-logo/`, body);
      toast.success(done);
      onDone();
    } catch (caught) {
      toast.error("Could not save that", caught instanceof ApiError ? caught.message : "Please try again.");
      setBusy("");
    }
  }

  return (
    <div className="space-y-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-3">
        <ServiceLogo name={row.name} slug={row.slug} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-ink">
            {row.name}
            {row.is_popular ? <Badge tone="info" className="ml-2 align-middle">Popular</Badge> : null}
          </p>
          <p className="code truncate text-caption text-ink-muted">{row.slug}</p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          loading={busy === "none"}
          disabled={Boolean(busy)}
          onClick={() => decide({ none: true }, `${row.name}: no official logo`, "none")}
        >
          None of these
        </Button>
      </div>

      {!enabled ? null : error ? (
        <p className="text-sm text-danger-700">
          {error instanceof ApiError ? error.message : "Could not search Brandfetch."}{" "}
          <button type="button" className="link" onClick={() => mutate()}>
            Try again
          </button>
        </p>
      ) : isLoading || !data ? (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((key) => (
            <Skeleton key={key} className="h-16" />
          ))}
        </div>
      ) : data.results.length === 0 ? (
        <p className="text-sm text-ink-muted">Brandfetch knows no brand called &ldquo;{data.query}&rdquo;.</p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {data.results.map((candidate) => (
            <CandidateCard
              key={candidate.domain}
              candidate={candidate}
              exact={sameName(candidate.name, row.name)}
              busy={busy === candidate.domain}
              disabled={Boolean(busy)}
              onUse={() =>
                decide({ domain: candidate.domain }, `${row.name}: logo from ${candidate.domain}`, candidate.domain)
              }
            />
          ))}
        </ul>
      )}

      {enabled ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <form
            className="flex flex-1 gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (draft.trim()) setQuery(draft.trim());
            }}
          >
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-label={`Search Brandfetch for ${row.name}`}
              className="h-9 text-sm"
            />
            <Button type="submit" variant="secondary" size="sm">
              Search
            </Button>
          </form>
          <form
            className="flex flex-1 gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (website.trim()) {
                void decide({ domain: website.trim() }, `${row.name}: logo from ${website.trim()}`, "website");
              }
            }}
          >
            <Input
              value={website}
              onChange={(event) => setWebsite(event.target.value)}
              placeholder="Or its website, e.g. venmo.com"
              aria-label={`Website of ${row.name}`}
              className="h-9 text-sm"
            />
            <Button type="submit" size="sm" loading={busy === "website"} disabled={Boolean(busy) || !website.trim()}>
              Use
            </Button>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function CandidateCard({
  candidate,
  exact,
  busy,
  disabled,
  onUse,
}: {
  candidate: Candidate;
  exact: boolean;
  busy: boolean;
  disabled: boolean;
  onUse: () => void;
}) {
  // Brandfetch answers 404 for a brand with no logo: there is nothing to use.
  const [missing, setMissing] = React.useState(false);

  return (
    <li className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3">
      {missing ? (
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sunken text-2xs text-ink-faint">
          none
        </span>
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- Brandfetch requires hotlinking its CDN
        <img
          src={candidate.logo_url}
          alt=""
          width={40}
          height={40}
          loading="lazy"
          onError={() => setMissing(true)}
          className="h-10 w-10 shrink-0 rounded-xl object-cover ring-1 ring-ink/10"
        />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink" title={candidate.name}>
          {candidate.name}
        </p>
        <p className="truncate text-caption text-ink-muted">{candidate.domain}</p>
        <p className="mt-1 flex flex-wrap gap-1">
          {exact ? <Badge tone="success">Same name</Badge> : null}
          {candidate.claimed ? <Badge tone="info">Claimed by the brand</Badge> : null}
        </p>
      </div>
      <Button size="sm" variant={exact ? "primary" : "secondary"} loading={busy} disabled={disabled || missing} onClick={onUse}>
        Use
      </Button>
    </li>
  );
}
