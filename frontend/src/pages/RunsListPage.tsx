import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select } from '@/components/ui/select';
import { useRuns } from '@/lib/queries';
import type { RunStatus } from '@/types/api';

const STATUS_VARIANT: Record<RunStatus, 'default' | 'good' | 'warn' | 'destructive'> = {
  queued: 'default',
  provisioning: 'warn',
  running: 'warn',
  passed: 'good',
  failed: 'destructive',
  error: 'destructive',
  canceled: 'default',
};

const PAGE_SIZE = 20;

export function RunsListPage() {
  const { t } = useTranslation();
  const [status, setStatus] = useState('');
  const [platform, setPlatform] = useState('');
  const [offset, setOffset] = useState(0);

  const { data, isLoading } = useRuns({
    status: status || undefined,
    platform: platform || undefined,
    limit: PAGE_SIZE,
    offset,
  });

  const runs = data?.runs ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t('nav.runs')}</h1>
          <p className="text-muted-foreground">{t('runsList.subtitle')}</p>
        </div>
        <Button asChild>
          <Link to="/runs/new">{t('nav.newRun')}</Link>
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        <Select value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className="w-auto">
          <option value="">{t('runsList.allStatuses')}</option>
          <option value="queued">queued</option>
          <option value="running">running</option>
          <option value="passed">passed</option>
          <option value="failed">failed</option>
          <option value="error">error</option>
          <option value="canceled">canceled</option>
        </Select>
        <Select value={platform} onChange={(e) => { setPlatform(e.target.value); setOffset(0); }} className="w-auto">
          <option value="">{t('runsList.allPlatforms')}</option>
          <option value="web">web</option>
          <option value="android">android</option>
          <option value="ios">ios</option>
        </Select>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t('runsList.title', { count: total })}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {isLoading && <p className="text-muted-foreground">{t('runsList.loading')}</p>}
          {!isLoading && runs.length === 0 && <p className="text-muted-foreground">{t('runsList.empty')}</p>}
          {runs.map((run) => (
            <Link
              key={run.id}
              to={`/runs/${run.id}`}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 hover:bg-muted transition-colors"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Badge variant={STATUS_VARIANT[run.status]}>{run.status}</Badge>
                  <span className="text-sm text-muted-foreground">{run.platform}</span>
                </div>
                <p className="truncate text-sm">{run.app_url || run.binary_url || run.id}</p>
              </div>
              <div className="text-sm text-muted-foreground">
                {run.scenarios_total > 0 && `${run.scenarios_passed}/${run.scenarios_total} ${t('runsList.scenarios')}`}
              </div>
            </Link>
          ))}
        </CardContent>
      </Card>

      {total > PAGE_SIZE && (
        <div className="flex justify-center gap-2">
          <Button variant="outline" disabled={offset === 0} onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}>
            {t('runsList.previous')}
          </Button>
          <Button variant="outline" disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset((o) => o + PAGE_SIZE)}>
            {t('runsList.next')}
          </Button>
        </div>
      )}
    </div>
  );
}
