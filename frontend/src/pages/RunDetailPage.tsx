import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api } from '@/lib/api';
import { useCancelRun, useRun } from '@/lib/queries';
import { useRunStream } from '@/lib/useRunStream';
import { TERMINAL_RUN_STATUSES } from '@/types/api';
import type { RunStatus, Scenario, ScenarioStatus, Step, StepStatus } from '@/types/api';

const STATUS_VARIANT: Record<RunStatus | ScenarioStatus | StepStatus, 'default' | 'good' | 'warn' | 'destructive'> = {
  queued: 'default',
  pending: 'default',
  provisioning: 'warn',
  running: 'warn',
  passed: 'good',
  failed: 'destructive',
  error: 'destructive',
  canceled: 'default',
  skipped: 'default',
};

function StepRow({ step }: { step: Step }) {
  return (
    <div className="border-l-2 border-border pl-3 py-1.5">
      <div className="flex items-center gap-2">
        <span className="font-medium text-sm">{step.keyword}</span>
        <span className="text-sm">{step.text}</span>
        <Badge variant={STATUS_VARIANT[step.status]}>{step.status}</Badge>
      </div>
      {step.error && <p className="text-xs text-destructive mt-1">{step.error}</p>}
      {step.evidences.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-2">
          {step.evidences.map((ev) => (
            <a key={ev.id} href={api.evidenceUrl(ev.id)} target="_blank" rel="noreferrer">
              <img src={api.evidenceUrl(ev.id)} alt={ev.label} className="h-16 w-auto rounded border border-border" />
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function ScenarioCard({ scenario }: { scenario: Scenario }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <CardTitle className="text-base">{scenario.name}</CardTitle>
          <Badge variant={STATUS_VARIANT[scenario.status]}>{scenario.status}</Badge>
        </div>
        {scenario.failure_reason && <p className="text-sm text-destructive">{scenario.failure_reason}</p>}
      </CardHeader>
      <CardContent className="space-y-1">
        {scenario.steps.map((step) => (
          <StepRow key={step.id} step={step} />
        ))}
      </CardContent>
    </Card>
  );
}

export function RunDetailPage() {
  const { t } = useTranslation();
  const { runId } = useParams<{ runId: string }>();
  const { data: run } = useRun(runId);
  const { log, connected } = useRunStream(runId);
  const cancelRun = useCancelRun();

  if (!run) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-8">
        <p className="text-muted-foreground">{t('runDetail.loading')}</p>
      </div>
    );
  }

  const isTerminal = TERMINAL_RUN_STATUSES.includes(run.status);

  async function handleCancel() {
    try {
      await cancelRun.mutateAsync(runId!);
      toast.success(t('runDetail.cancelled'));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-semibold">{t('runDetail.title')}</h1>
            <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
            {!isTerminal && (
              <span
                className={`inline-block h-2 w-2 rounded-full ${connected ? 'bg-[hsl(var(--good))]' : 'bg-muted-foreground'}`}
                title={connected ? t('runDetail.live') : t('runDetail.reconnecting')}
              />
            )}
          </div>
          <p className="text-muted-foreground text-sm">{run.app_url || run.binary_url}</p>
        </div>
        <div className="flex gap-2">
          {!isTerminal && (
            <Button variant="destructive" onClick={handleCancel} disabled={run.cancel_requested || cancelRun.isPending}>
              {run.cancel_requested ? t('runDetail.cancelling') : t('runDetail.cancel')}
            </Button>
          )}
          {isTerminal && (
            <>
              <Button variant="outline" asChild>
                <a href={api.reportUrl(run.id)} target="_blank" rel="noreferrer">{t('runDetail.viewReport')}</a>
              </Button>
              <Button variant="outline" asChild>
                <a href={api.artifactsZipUrl(run.id)}>{t('runDetail.downloadArtifacts')}</a>
              </Button>
            </>
          )}
        </div>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-3 pt-6 text-sm sm:grid-cols-4">
          <div><span className="text-muted-foreground">{t('newRun.platform')}: </span>{run.platform}</div>
          <div><span className="text-muted-foreground">Provider: </span>{run.llm_provider}/{run.llm_model}</div>
          <div><span className="text-muted-foreground">{t('runsList.scenarios')}: </span>{run.scenarios_passed}/{run.scenarios_total}</div>
          <div><span className="text-muted-foreground">Custo: </span>${run.cost_usd.toFixed(4)}</div>
        </CardContent>
      </Card>

      {run.error && (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-destructive">{run.error}</p>
          </CardContent>
        </Card>
      )}

      <div className="space-y-4">
        {run.scenarios.map((scenario) => (
          <ScenarioCard key={scenario.id} scenario={scenario} />
        ))}
        {run.scenarios.length === 0 && (
          <p className="text-muted-foreground text-sm">{t('runDetail.noScenariosYet')}</p>
        )}
      </div>

      {log.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t('runDetail.eventLog')}</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="max-h-48 overflow-y-auto font-mono text-xs space-y-1">
              {log.map((entry, i) => (
                <div key={i} className="text-muted-foreground">
                  {entry.type}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
