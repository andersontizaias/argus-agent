import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { useApiKeys, useConfig, useCreateApiKey, useHealth, useRevokeApiKey, useSaveConfig, useTestLlmProvider } from '@/lib/queries';
import type { ProjectConfig } from '@/types/api';

// Lista declarativa dos providers LLM suportados — mesmo padrão do
// ConfigPage do phalanx-agents: adicionar um provider novo é uma linha
// aqui (o backend já resolve via src/llm_providers.py).
const LLM_PROVIDERS: {
  id: string;
  label: string;
  apiKeyField: keyof ProjectConfig;
  needsBaseUrl?: boolean;
  baseUrlField?: keyof ProjectConfig;
  baseUrlPlaceholder?: string;
  helpText?: string;
  timeoutField?: keyof ProjectConfig;
}[] = [
  { id: 'anthropic', label: 'Anthropic', apiKeyField: 'anthropic_api_key' },
  { id: 'openai', label: 'OpenAI', apiKeyField: 'openai_api_key' },
  { id: 'google_genai', label: 'Google Gemini', apiKeyField: 'gemini_api_key' },
  { id: 'groq', label: 'Groq', apiKeyField: 'groq_api_key' },
  {
    id: 'ollama', label: 'Ollama (local ou remoto)', apiKeyField: 'ollama_api_key',
    needsBaseUrl: true, baseUrlField: 'ollama_base_url',
    baseUrlPlaceholder: 'http://localhost:11434 ou http://<host-remoto>:11434',
    helpText: 'A chave de API é opcional — só necessária se o servidor Ollama estiver atrás de um proxy com autenticação (Bearer token).',
    timeoutField: 'ollama_timeout_seconds',
  },
  { id: 'custom', label: 'Custom (compatível com OpenAI)', apiKeyField: 'custom_llm_api_key', needsBaseUrl: true, baseUrlField: 'custom_llm_base_url' },
];

function ApiKeysSection() {
  const { t } = useTranslation();
  const { data: keys } = useApiKeys();
  const createKey = useCreateApiKey();
  const revokeKey = useRevokeApiKey();
  const [name, setName] = useState('');
  const [justCreatedKey, setJustCreatedKey] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) return;
    try {
      const created = await createKey.mutateAsync(name.trim());
      setJustCreatedKey(created.key);
      setName('');
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRevoke(keyId: string) {
    try {
      await revokeKey.mutateAsync(keyId);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('config.apiKeys')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">{t('config.apiKeysHelp')}</p>

        {justCreatedKey && (
          <div className="rounded-md border border-[hsl(var(--warn))] bg-[hsl(var(--warn)/0.1)] p-3 space-y-1">
            <p className="text-sm font-medium">{t('config.apiKeyShownOnce')}</p>
            <code className="block break-all rounded bg-background/50 p-2 text-xs">{justCreatedKey}</code>
            <Button variant="ghost" size="sm" onClick={() => setJustCreatedKey(null)}>{t('config.apiKeyDismiss')}</Button>
          </div>
        )}

        <div className="flex gap-2">
          <Input placeholder={t('config.apiKeyNamePlaceholder')} value={name} onChange={(e) => setName(e.target.value)} className="flex-1" />
          <Button onClick={handleCreate} disabled={createKey.isPending || !name.trim()}>
            {createKey.isPending ? t('config.creating') : t('config.apiKeyCreate')}
          </Button>
        </div>

        <div className="space-y-2">
          {(Array.isArray(keys) ? keys : []).map((key) => (
            <div key={key.id} className="flex items-center justify-between gap-2 rounded-md border border-border p-2 text-sm">
              <div>
                <span className="font-medium">{key.name}</span>{' '}
                <span className="text-muted-foreground">argus_{key.prefix}_...</span>
                {key.revoked && <Badge variant="destructive" className="ml-2">{t('config.apiKeyRevoked')}</Badge>}
              </div>
              {!key.revoked && (
                <Button variant="ghost" size="sm" onClick={() => handleRevoke(key.id)} disabled={revokeKey.isPending}>
                  {t('config.apiKeyRevoke')}
                </Button>
              )}
            </div>
          ))}
          {Array.isArray(keys) && keys.length === 0 && <p className="text-sm text-muted-foreground">{t('config.apiKeysEmpty')}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

export function ConfigPage() {
  const { t } = useTranslation();
  const { data: config } = useConfig();
  const { data: health } = useHealth();
  const saveConfig = useSaveConfig();
  const testProvider = useTestLlmProvider();

  const [values, setValues] = useState<Partial<ProjectConfig>>({});
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({});

  useEffect(() => {
    if (config) setValues(config);
  }, [config]);

  function field(key: keyof ProjectConfig) {
    return values[key] ?? '';
  }

  function setField(key: keyof ProjectConfig, value: string) {
    setValues((v) => ({ ...v, [key]: value }));
  }

  async function handleSave() {
    try {
      await saveConfig.mutateAsync(values);
      toast.success(t('config.saved'));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleTest(providerId: string) {
    try {
      // "Testar provider" precisa testar o que está na tela agora, não o
      // que já estava salvo antes — sem isso, digitar uma chave/URL nova e
      // clicar em testar sem salvar primeiro sempre dava "não configurado".
      await saveConfig.mutateAsync(values);
      const result = await testProvider.mutateAsync(providerId);
      setTestResults((r) => ({ ...r, [providerId]: { ok: !!result.ok, message: result.ok ? t('config.testOk') : result.error || t('config.testFail') } }));
    } catch (e) {
      setTestResults((r) => ({ ...r, [providerId]: { ok: false, message: e instanceof Error ? e.message : String(e) } }));
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{t('config.title')}</h1>
        <p className="text-muted-foreground">{t('config.subtitle')}</p>
      </div>

      {health && (
        <Card>
          <CardHeader>
            <CardTitle>{t('health.title')}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {health.checks.map((c) => (
              <Badge key={c.name} variant={c.ok ? 'good' : 'warn'} title={c.detail}>
                {c.name} {c.ok ? '✓' : '✗'}
              </Badge>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>{t('config.providers')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          {LLM_PROVIDERS.map((provider) => (
            <div key={provider.id} className="space-y-2 border-b border-border pb-4 last:border-0 last:pb-0">
              <Label>{provider.label}</Label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input
                  type="password"
                  placeholder={t('config.apiKey')}
                  value={field(provider.apiKeyField)}
                  onChange={(e) => setField(provider.apiKeyField, e.target.value)}
                  className="sm:flex-1"
                />
                {provider.needsBaseUrl && provider.baseUrlField && (
                  <Input
                    type="text"
                    placeholder={provider.baseUrlPlaceholder ?? t('config.baseUrl')}
                    value={field(provider.baseUrlField)}
                    onChange={(e) => setField(provider.baseUrlField!, e.target.value)}
                    className="sm:flex-1"
                  />
                )}
                {provider.timeoutField && (
                  <Input
                    type="text"
                    inputMode="numeric"
                    placeholder="300"
                    title={t('config.timeoutSeconds')}
                    value={field(provider.timeoutField)}
                    onChange={(e) => setField(provider.timeoutField!, e.target.value.replace(/\D/g, ''))}
                    className="sm:w-28"
                  />
                )}
                <Button
                  variant="outline"
                  onClick={() => handleTest(provider.id)}
                  disabled={testProvider.isPending || saveConfig.isPending}
                >
                  {testProvider.isPending || saveConfig.isPending ? t('config.testing') : t('config.testProvider')}
                </Button>
              </div>
              {provider.helpText && <p className="text-xs text-muted-foreground">{provider.helpText}</p>}
              {testResults[provider.id] && (
                <p className={testResults[provider.id].ok ? 'text-sm text-[hsl(var(--good))]' : 'text-sm text-destructive'}>
                  {testResults[provider.id].message}
                </p>
              )}
            </div>
          ))}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>{t('config.defaultProvider')}</Label>
              <Input
                value={field('default_llm_provider')}
                onChange={(e) => setField('default_llm_provider', e.target.value)}
                placeholder="anthropic"
              />
            </div>
            <div className="space-y-2">
              <Label>{t('config.defaultModel')}</Label>
              <Input
                value={field('default_llm_model')}
                onChange={(e) => setField('default_llm_model', e.target.value)}
                placeholder="claude-3-5-haiku-latest"
              />
            </div>
          </div>

          <Button onClick={handleSave} disabled={saveConfig.isPending}>
            {saveConfig.isPending ? t('config.saving') : t('config.save')}
          </Button>
        </CardContent>
      </Card>

      <ApiKeysSection />
    </div>
  );
}
