"use client";

import * as React from "react";
import useSWR from "swr";

import { Pagination } from "@/components/admin/pagination";
import { AdminToolbar, KpiCard, KpiRow, ListCard, SearchBox } from "@/components/admin/ui";
import { PageHeader } from "@/components/app-shell";
import { CheckCircleIcon, GridIcon, SearchIcon, StarIcon } from "@/components/icons";
import { ServiceLogo } from "@/components/service-logo";
import { Dialog } from "@/components/ui/dialog";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
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

  const { data, error, isLoading, isValidating, mutate } = useSWR<Queue>(
    ["/admin/services/logo-queue/", { page, search: debounced }],
    { keepPreviousData: true },
  );

  // What each row's live search found, and which of those logos did not load.
  const [found, setFound] = React.useState<Record<string, Candidate[]>>({});
  const [missing, setMissing] = React.useState<Record<string, true>>({});
  const [reviewing, setReviewing] = React.useState(false);
  const onFound = React.useCallback((slug: string, results: Candidate[]) => {
    setFound((current) => ({ ...current, [slug]: results }));
  }, []);
  const onMissing = React.useCallback((domain: string) => {
    setMissing((current) => (current[domain] ? current : { ...current, [domain]: true }));
  }, []);

  const picks = (data?.results ?? [])
    .map((row) => ({ row, choice: claimedChoice(row, found[row.slug], missing) }))
    .filter((item): item is { row: QueueRow; choice: Candidate } => item.choice !== null);

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

      <KpiRow>
        <KpiCard
          icon={<StarIcon />}
          tone="gold"
          label="Waiting for a logo"
          value={data?.count}
          hint="On sale, showing the generic tile"
        />
        <KpiCard
          icon={<CheckCircleIcon />}
          label="One-click matches"
          value={data ? picks.length : undefined}
          hint="Brand-claimed, on this page"
          onClick={data?.configured && picks.length ? () => setReviewing(true) : undefined}
        />
        <KpiCard
          icon={<SearchIcon />}
          tone="info"
          label="Logo source"
          value={data ? (data.configured ? "Brandfetch" : "Not set up") : undefined}
          hint="Official brand logos"
        />
        <KpiCard
          icon={<GridIcon />}
          tone="neutral"
          label="Pages to review"
          value={data?.pages}
          hint="25 services a page"
        />
      </KpiRow>

      <AdminToolbar>
        <p className="px-1 text-sm text-ink-muted lg:flex-1">
          Pick the right company for each service, or say none of them is.
        </p>
        {data?.configured ? (
          <Button
            variant="primary"
            disabled={picks.length === 0}
            onClick={() => setReviewing(true)}
            className="shrink-0"
            icon={<CheckCircleIcon className="h-4 w-4" />}
          >
            Use claimed brands ({picks.length})
          </Button>
        ) : null}
        <SearchBox label="Find a service" placeholder="Find a service" value={search} onChange={setSearch} />
      </AdminToolbar>

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
        <ListCard
          title="Services without a logo"
          count={data.count}
          noun="services"
          refreshing={isValidating}
          onRefresh={() => mutate()}
        >
          <div className="divide-y divide-line">
          {data.results.map((row) => (
            <QueueItem
              key={row.slug}
              row={row}
              enabled={data.configured}
              onDone={() => mutate()}
              onFound={onFound}
              onMissing={onMissing}
            />
          ))}
          </div>
        </ListCard>
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

      <ClaimedReview
        open={reviewing}
        picks={picks}
        onClose={() => setReviewing(false)}
        onDone={() => {
          setReviewing(false);
          void mutate();
        }}
      />
    </div>
  );
}

/**
 * The brand-claimed match for one service, when one click can safely decide it:
 * the one claimed brand, or - if several are claimed - the one with exactly
 * the service's name. None when it is ambiguous, or its logo did not load.
 */
function claimedChoice(
  row: QueueRow,
  candidates: Candidate[] | undefined,
  missing: Record<string, true>,
): Candidate | null {
  const claimed = (candidates ?? []).filter((candidate) => candidate.claimed && !missing[candidate.domain]);
  if (claimed.length === 1) return claimed[0];
  const named = claimed.filter((candidate) => sameName(candidate.name, row.name));
  return named.length === 1 ? named[0] : null;
}

/** Confirm the claimed brands for this page, untick any that look wrong, then apply. */
function ClaimedReview({
  open,
  picks,
  onClose,
  onDone,
}: {
  open: boolean;
  picks: { row: QueueRow; choice: Candidate }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [chosen, setChosen] = React.useState<Record<string, boolean>>({});
  const [progress, setProgress] = React.useState<{ done: number; failed: number } | null>(null);

  React.useEffect(() => {
    if (open) {
      setChosen(Object.fromEntries(picks.map(({ row }) => [row.slug, true])));
      setProgress(null);
    }
    // Only when the dialog opens: picks keep arriving as rows finish searching.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const selected = picks.filter(({ row }) => chosen[row.slug]);
  const running = progress !== null;

  async function apply() {
    let done = 0;
    let failed = 0;
    setProgress({ done, failed });
    // One at a time: each is its own audited decision.
    for (const { row, choice } of selected) {
      try {
        await api.post(`/admin/services/${row.slug}/brand-logo/`, {
          domain: choice.domain,
          reason: `Brand-claimed match on Brandfetch: ${choice.domain}`,
        });
        done += 1;
      } catch {
        failed += 1;
      }
      setProgress({ done, failed });
    }
    if (failed) toast.error(`${done} logos set, ${failed} failed`, "The failed ones are still in the queue.");
    else toast.success(`${done} logos set`, "Each is in the audit log.");
    onDone();
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Use the brand-claimed logos?"
      description="For each service below, the logo of the one company that claimed its own Brandfetch profile. Untick any that is not the right company."
      dismissible={!running}
    >
      <div className="space-y-4">
        <ul className="max-h-[50vh] divide-y divide-line overflow-y-auto rounded-xl border border-line">
          {picks.map(({ row, choice }) => {
            const different = !sameName(choice.name, row.name);
            return (
              <li key={row.slug} className="flex items-center gap-3 px-3 py-2.5">
                <Checkbox
                  id={`claimed-${row.slug}`}
                  checked={Boolean(chosen[row.slug])}
                  disabled={running}
                  onChange={(event) => setChosen((current) => ({ ...current, [row.slug]: event.target.checked }))}
                  label={
                    <span className="flex items-center gap-3">
                      {/* eslint-disable-next-line @next/next/no-img-element -- Brandfetch requires hotlinking its CDN */}
                      <img src={choice.logo_url} alt="" width={32} height={32} className="h-8 w-8 rounded-lg ring-1 ring-ink/10" />
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-medium text-ink">{row.name}</span>
                        <span className="block truncate text-caption text-ink-muted">
                          {choice.name} - {choice.domain}
                        </span>
                      </span>
                    </span>
                  }
                />
                {different ? <Badge tone="warn" className="ml-auto shrink-0">Different name</Badge> : null}
              </li>
            );
          })}
        </ul>
        <p className="text-caption text-ink-muted">
          Services with several claimed companies, or none, are left for you to decide one by one.
        </p>
        <div className="flex items-center justify-end gap-2">
          {progress ? (
            <span className="mr-auto text-sm text-ink-muted">
              {progress.done + progress.failed} of {selected.length} done
            </span>
          ) : null}
          <Button variant="secondary" onClick={onClose} disabled={running}>
            Cancel
          </Button>
          <Button onClick={apply} loading={running} disabled={selected.length === 0}>
            Use {selected.length} {selected.length === 1 ? "logo" : "logos"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

function QueueItem({
  row,
  enabled,
  onDone,
  onFound,
  onMissing,
}: {
  row: QueueRow;
  enabled: boolean;
  onDone: () => void;
  onFound: (slug: string, results: Candidate[]) => void;
  onMissing: (domain: string) => void;
}) {
  const toast = useToast();
  const [query, setQuery] = React.useState(row.name);
  const [draft, setDraft] = React.useState(row.name);
  const [website, setWebsite] = React.useState("");
  const [busy, setBusy] = React.useState("");

  const { data, error, isLoading, mutate } = useSWR<{ query: string; results: Candidate[] }>(
    enabled ? [`/admin/services/${row.slug}/logo-candidates/`, { q: query }] : null,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  React.useEffect(() => {
    if (data) onFound(row.slug, data.results);
  }, [data, row.slug, onFound]);

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
              onMissing={() => onMissing(candidate.domain)}
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
  onMissing,
}: {
  candidate: Candidate;
  exact: boolean;
  busy: boolean;
  disabled: boolean;
  onUse: () => void;
  onMissing: () => void;
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
          onError={() => {
            setMissing(true);
            onMissing();
          }}
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
