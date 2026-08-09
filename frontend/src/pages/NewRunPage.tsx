import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Upload } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useConfig, useCreateRun } from '@/lib/queries';
import { ApiError } from '@/lib/api';
import { isProviderConfigured, LLM_PROVIDERS } from '@/lib/llmProviders';
import type { RunPlatform } from '@/types/api';

const BDD_PLACEHOLDER = `# language: pt
Funcionalidade: Login
  Cenário: Login válido
    Dado que estou na página de login
    Quando preencho usuário "standard_user"
    E preencho senha "secret_sauce"
    E clico em entrar
    Então vejo a lista de produtos`;

/** Lê um <input type="file"> como texto e entrega pro callback — usado
 * pelos dois botões de upload (BDD e massa de testes). Reseta o próprio
 * input ao final pra que escolher o MESMO arquivo de novo (depois de editar
 * o campo manualmente) ainda dispare onChange na próxima vez. */
function readUploadedFile(e: React.ChangeEvent<HTMLInputElement>, onText: (text: string) => void, onError: () => void) {
  const file = e.target.files?.[0];
  const input = e.target;
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    onText(String(reader.result ?? ''));
    input.value = '';
  };
  reader.onerror = () => {
    onError();
    input.value = '';
  };
  reader.readAsText(file);
}

export function NewRunPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const createRun = useCreateRun();
  const { data: config } = useConfig();

  const [platform, setPlatform] = useState<RunPlatform>('web');
  const [appUrl, setAppUrl] = useState('');
  const [binaryUrl, setBinaryUrl] = useState('');
  const [binaryAuthSecret, setBinaryAuthSecret] = useState('');
  const [bddScript, setBddScript] = useState('');
  const [testDataJson, setTestDataJson] = useState('{}');
  const [llmProvider, setLlmProvider] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const bddFileInputRef = useRef<HTMLInputElement>(null);
  const testDataFileInputRef = useRef<HTMLInputElement>(null);

  function handleBddFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    readUploadedFile(e, setBddScript, () => toast.error(t('newRun.fileReadError')));
  }

  function handleTestDataFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    readUploadedFile(
      e,
      (text) => {
        setTestDataJson(text);
        try {
          JSON.parse(text);
        } catch {
          toast.error(t('newRun.invalidJson'));
        }
      },
      () => toast.error(t('newRun.fileReadError'))
    );
  }

  function handleProviderChange(id: string) {
    setLlmProvider(id);
    if (!id) {
      setLlmModel('');
      return;
    }
    // Não existe uma lista de "modelos cadastrados" por provider (só um
    // default global) — se o provider escolhido é o default configurado,
    // sugere o modelo default; senão, o exemplo do provider. Continua um
    // campo editável, não trava no sugerido.
    const provider = LLM_PROVIDERS.find((p) => p.id === id);
    if (id === config?.default_llm_provider && config?.default_llm_model) {
      setLlmModel(config.default_llm_model);
    } else {
      setLlmModel(provider?.exampleModel ?? '');
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    let testData: Record<string, string>;
    try {
      const parsed = testDataJson.trim() ? JSON.parse(testDataJson) : {};
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
        throw new Error(t('newRun.testDataMustBeObject'));
      }
      testData = parsed;
    } catch {
      setFormError(t('newRun.invalidJson'));
      return;
    }

    try {
      const run = await createRun.mutateAsync({
        platform,
        app_url: platform === 'web' ? appUrl || undefined : undefined,
        binary_url: platform !== 'web' ? binaryUrl || undefined : undefined,
        binary_auth_secret: platform !== 'web' ? binaryAuthSecret || undefined : undefined,
        bdd_script: bddScript,
        test_data: testData,
        llm_provider: llmProvider || undefined,
        llm_model: llmModel || undefined,
      });
      toast.success(t('newRun.created'));
      navigate(`/runs/${run.id}`);
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : String(err));
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <h1 className="text-2xl font-semibold">{t('newRun.title')}</h1>
          <p className="text-muted-foreground">{t('newRun.subtitle')}</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>{t('newRun.target')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="platform">{t('newRun.platform')}</Label>
              <Select
                id="platform"
                value={platform}
                onChange={(e) => setPlatform(e.target.value as RunPlatform)}
              >
                <option value="web">Web</option>
                <option value="android">Android</option>
                <option value="ios">iOS</option>
              </Select>
            </div>

            {platform === 'web' ? (
              <div className="space-y-2">
                <Label htmlFor="app-url">{t('newRun.appUrl')}</Label>
                <Input
                  id="app-url"
                  type="url"
                  placeholder="https://exemplo.com"
                  value={appUrl}
                  onChange={(e) => setAppUrl(e.target.value)}
                  required
                />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <Label htmlFor="binary-url">{t('newRun.binaryUrl')}</Label>
                  <Input
                    id="binary-url"
                    type="url"
                    placeholder="https://exemplo.com/app.apk"
                    value={binaryUrl}
                    onChange={(e) => setBinaryUrl(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="binary-secret">{t('newRun.binaryAuthSecret')}</Label>
                  <Input
                    id="binary-secret"
                    placeholder={t('newRun.binaryAuthSecretPlaceholder')}
                    value={binaryAuthSecret}
                    onChange={(e) => setBinaryAuthSecret(e.target.value)}
                  />
                </div>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('newRun.bddScript')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-end">
                <input
                  ref={bddFileInputRef}
                  type="file"
                  accept=".feature,.txt,text/plain"
                  aria-label={t('newRun.uploadBddFile')}
                  className="hidden"
                  onChange={handleBddFileChange}
                />
                <Button type="button" variant="outline" size="sm" onClick={() => bddFileInputRef.current?.click()}>
                  <Upload className="h-4 w-4" />
                  {t('newRun.uploadBddFile')}
                </Button>
              </div>
              <Textarea
                aria-label={t('newRun.bddScript')}
                rows={12}
                placeholder={BDD_PLACEHOLDER}
                value={bddScript}
                onChange={(e) => setBddScript(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="test-data">{t('newRun.testData')}</Label>
                <input
                  ref={testDataFileInputRef}
                  type="file"
                  accept=".json,application/json"
                  aria-label={t('newRun.uploadTestDataFile')}
                  className="hidden"
                  onChange={handleTestDataFileChange}
                />
                <Button type="button" variant="outline" size="sm" onClick={() => testDataFileInputRef.current?.click()}>
                  <Upload className="h-4 w-4" />
                  {t('newRun.uploadTestDataFile')}
                </Button>
              </div>
              <Textarea
                id="test-data"
                rows={4}
                placeholder='{"usuario_valido": "standard_user"}'
                value={testDataJson}
                onChange={(e) => setTestDataJson(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('newRun.llmOverride')}</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="llm-provider">{t('config.defaultProvider')}</Label>
              <Select id="llm-provider" value={llmProvider} onChange={(e) => handleProviderChange(e.target.value)}>
                <option value="">{t('newRun.useDefault')}</option>
                {LLM_PROVIDERS.map((provider) => {
                  const configured = isProviderConfigured(provider, config);
                  return (
                    <option key={provider.id} value={provider.id} disabled={!configured}>
                      {provider.label}
                      {!configured ? ` (${t('newRun.providerNotConfigured')})` : ''}
                    </option>
                  );
                })}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="llm-model">{t('config.defaultModel')}</Label>
              <Input id="llm-model" placeholder={t('newRun.useDefault')} value={llmModel} onChange={(e) => setLlmModel(e.target.value)} />
            </div>
          </CardContent>
        </Card>

        {formError && <p className="text-sm text-destructive">{formError}</p>}

        <Button type="submit" disabled={createRun.isPending}>
          {createRun.isPending ? t('newRun.creating') : t('newRun.create')}
        </Button>
      </form>
    </div>
  );
}
