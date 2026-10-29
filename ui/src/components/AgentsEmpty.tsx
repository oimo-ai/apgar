import { ExternalLink, Lock, Plus } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { DOCS_URL } from "@/lib/links";

const STEPS = [
  ["Traces arrive", "Apgar groups spans into turns and reads the release from each trace."],
  ["First release", "It has nothing to compare with yet, so it becomes the baseline."],
  ["Next release", "Once it has enough turns, Apgar compares it with the baseline and reports Regression or Healthy, on the release page and in Slack or a webhook."],
] as const;

function Path({ title, children, actions }: { title: string; children: ReactNode; actions: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 p-4">
      <div>
        <h4 className="m-0 text-sm font-semibold">{title}</h4>
        <p className="m-0 mt-1 text-muted-foreground">{children}</p>
      </div>
      <div className="mt-auto flex flex-wrap items-center gap-3">{actions}</div>
    </div>
  );
}

export function AgentsEmpty({ seeding, onAdd, onSeed }: { seeding: boolean; onAdd: () => void; onSeed: () => void }) {
  return (
    <div data-testid="agents-empty" className="flex flex-col gap-4">
      <Panel>
        <PanelHeader
          title="No agents yet"
          description="Apgar compares each new release of an agent with the previous one and tells you whether it got worse: more tool errors, retries, cost, or latency."
        />
        <div className="grid divide-y divide-border md:grid-cols-2 md:divide-x md:divide-y-0">
          <Path
            title="Connect your agent"
            actions={
              <>
                <Button type="button" data-testid="empty-add-agent" onClick={onAdd}>
                  <Plus size={16} strokeWidth={2} aria-hidden="true" />
                  Add agent
                </Button>
                <a data-testid="empty-setup-guide" href={`${DOCS_URL}/quickstart`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sm">
                  Setup guide
                  <ExternalLink size={12} aria-hidden="true" />
                </a>
              </>
            }
          >
            Send traces over OTLP or pull them from Langfuse. Each trace needs a release attribute, such as <code className="mono">service.version</code>.
          </Path>
          <Path
            title="Explore with demo data"
            actions={
              <>
                <Button type="button" variant="outline" data-testid="seed-demo-button" disabled={seeding} onClick={onSeed}>
                  Load demo agents
                </Button>
                {seeding ? (
                  <span data-testid="seed-demo-progress" role="status" className="text-sm text-muted-foreground">
                    Loading demo agents…
                  </span>
                ) : null}
              </>
            }
          >
            Two agents with 14 days of generated releases, including regressions. They appear in a few seconds, and Apgar opens a
            regression once its verdict is in.
          </Path>
        </div>
      </Panel>
      <Panel>
        <PanelHeader title="What happens next" />
        <ol className="m-0 grid list-none gap-4 p-4 md:grid-cols-3">
          {STEPS.map(([title, body], index) => (
            <li key={title} className="flex gap-3">
              <span className="num inline-grid size-6 shrink-0 place-items-center rounded-full bg-muted text-xs font-semibold" aria-hidden="true">
                {index + 1}
              </span>
              <div>
                <p className="m-0 font-medium">{title}</p>
                <p className="m-0 mt-0.5 text-muted-foreground">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>
      <p data-testid="empty-privacy" className="m-0 inline-flex items-center gap-1.5 text-xs text-muted-foreground">
        <Lock size={12} aria-hidden="true" />
        Apgar never stores prompts, completions, or tool arguments.
      </p>
    </div>
  );
}
