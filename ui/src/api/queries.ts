import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch, onSessionCleared } from "@/api/client";
import type {
  AgentOut,
  ConnectionOut,
  EvaluationOut,
  IngestTokenOut,
  NotificationOut,
  Page,
  ReleaseDetail,
  ReleaseEventOut,
  ReleaseOut,
  SessionOut,
  SettingsOut,
  StatusOut,
} from "@/api/types";

let bound = false;

export function bindSessionCache(client: ReturnType<typeof useQueryClient>): void {
  if (bound) {
    return;
  }
  bound = true;
  onSessionCleared(() => {
    client.removeQueries({ queryKey: ["session"] });
  });
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => apiFetch<StatusOut>("/api/v1/status"),
    refetchInterval: 10_000,
  });
}

export function useSession() {
  return useQuery({
    queryKey: ["session"],
    queryFn: () => apiFetch<SessionOut>("/api/v1/auth/session", undefined, { redirectOn401: false }),
    retry: false,
  });
}

export function useAgents(seeding = false) {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiFetch<Page<AgentOut>>("/api/v1/agents?limit=500"),
    refetchInterval: seeding ? 5_000 : 30_000,
  });
}

export function useAgent(name: string) {
  return useQuery({
    queryKey: ["agent", name],
    queryFn: () => apiFetch<AgentOut>(`/api/v1/agents/${encodeURIComponent(name)}`),
    enabled: Boolean(name),
  });
}

export function useAgentReleases(agent: string) {
  return useQuery({
    queryKey: ["releases", { agent, scope: "agent" }],
    queryFn: () =>
      apiFetch<Page<ReleaseOut>>(`/api/v1/agents/${encodeURIComponent(agent)}/releases?limit=500`),
    enabled: Boolean(agent),
  });
}

const LIVE_HISTORY_MS = 60_000;

export function useRelease(agent: string, release: string, queued = false) {
  return useQuery({
    queryKey: ["release", agent, release],
    queryFn: () =>
      apiFetch<ReleaseDetail>(
        `/api/v1/agents/${encodeURIComponent(agent)}/releases/${encodeURIComponent(release)}`,
      ),
    enabled: Boolean(agent && release),
    refetchInterval: (query) => {
      if (queued) {
        return 2_000;
      }
      if (query.state.data && query.state.data.final === false) {
        return 15_000;
      }
      return false;
    },
  });
}

export function useEvaluations(agent: string, release: string, queued = false, live = false) {
  return useQuery({
    queryKey: ["evaluations", agent, release],
    queryFn: () =>
      apiFetch<Page<EvaluationOut>>(
        `/api/v1/agents/${encodeURIComponent(agent)}/releases/${encodeURIComponent(release)}/evaluations?limit=500`,
      ),
    enabled: Boolean(agent && release),
    refetchInterval: queued ? 2_000 : live ? LIVE_HISTORY_MS : false,
  });
}

export function useEvents(agent: string, release: string, queued = false, live = false) {
  return useQuery({
    queryKey: ["events", agent, release],
    queryFn: () =>
      apiFetch<{ items: ReleaseEventOut[] }>(
        `/api/v1/agents/${encodeURIComponent(agent)}/releases/${encodeURIComponent(release)}/events`,
      ),
    enabled: Boolean(agent && release),
    refetchInterval: queued ? 2_000 : live ? LIVE_HISTORY_MS : false,
  });
}

export function useNotifications(status: string, limit: number, offset: number) {
  return useQuery({
    queryKey: ["notifications", status, limit, offset],
    queryFn: () =>
      apiFetch<Page<NotificationOut>>(
        `/api/v1/notifications${qs({ status: status === "all" ? undefined : status, limit, offset })}`,
      ),
    refetchInterval: 5_000,
  });
}

export function useConnections() {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => apiFetch<Page<ConnectionOut>>("/api/v1/connections?limit=500"),
  });
}

export function useIngestTokens() {
  return useQuery({
    queryKey: ["ingest-tokens"],
    queryFn: () => apiFetch<Page<IngestTokenOut>>("/api/v1/ingest-tokens?limit=500"),
  });
}

export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: () => apiFetch<SettingsOut>("/api/v1/settings"),
  });
}

export function useInvalidate() {
  const client = useQueryClient();
  return async (keys: unknown[][]): Promise<void> => {
    await Promise.all(keys.map((queryKey) => client.invalidateQueries({ queryKey })));
  };
}

export function usePost(path: string) {
  return useMutation({
    mutationFn: (body?: unknown) =>
      apiFetch(path, {
        method: "POST",
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
  });
}
