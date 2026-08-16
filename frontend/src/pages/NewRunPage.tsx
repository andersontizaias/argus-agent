import { useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
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
import { api, ApiError } from '@/lib/api';
import { isProviderConfigured, LLM_PROVIDERS } from '@/lib/llmProviders';
import type { RunMode, RunPlatform } from '@/types/api';

const DEFAULT_EXPLORE_MAX_ACTIONS = 25;

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
  const location = useLocation();
  const createRun = useCreateRun();
  const { data: config } = useConfig();

  // Vindo do botão "Usar em Nova Execução" de uma run mode="explore" (ver
  // RunDetailPage) — pré-preenche o script gerado e já força modo Executar
  // (o script existe, não faz sentido abrir em modo Explorar).
  const prefillBddScript = (location.state as { prefillBddScript?: string } | null)?.prefillBddScript;

  const [mode, setMode] = useState<RunMode>('execute');
  const [platform, setPlatform] = useState<RunPlatform>('web');
  const [appUrl, setAppUrl] = useState('');
  const [binaryUrl, setBinaryUrl] = useState('');
  const [binaryAuthSecret, setBinaryAuthSecret] = useState('');
  const [binaryUploading, setBinaryUploading] = useState(false);
  const [bddScript, setBddScript] = useState(prefillBddScript ?? '');
  const [testDataJson, setTestDataJson] = useState('{}');
  const [llmProvider, setLlmProvider] = useState('');
  const [llmModel, setLlmModel] = useState('');
  const [maxActions, setMaxActions] = useState(String(DEFAULT_EXPLORE_MAX_ACTIONS));
  const [confirmedNonProduction, setConfirmedNonProduction] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const bddFileInputRef = useRef<HTMLInputElement>(null);
  const testDataFileInputRef = useRef<HTMLInputElement>(null);
  const binaryFileInputRef = useRef<HTMLInputElement>(null);

  function handleBddFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    readUploadedFile(e, setBddScript, () => toast.error(t('newRun.fileReadError')));
  }

  /** Sobe um .apk/.aab/.ipa/.zip local pro backend e usa o caminho
   * devolvido como binary_url — mesmo campo que já aceitava uma URL
   * http(s) (o backend reconhece um caminho local e copia em vez de
   * baixar, ver tools/binary_fetch.py). .aab é rejeitado ANTES de subir
   * (sem round-trip pra um arquivo potencialmente grande à toa): não é
   * instalável direto ainda (falta suporte a bundletool), então o upload
   * só resultaria numa run falhando depois, de forma mais confusa. */
  async function handleBinaryFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    const input = e.target;
    input.value = '';
    if (!file) return;

    if (file.name.toLowerCase().endsWith('.aab')) {
      toast.error(t('newRun.aabNotSupported'));
      return;
    }

    setBinaryUploading(true);
    try {
      const uploaded = await api.uploadBinary(file);
      setBinaryUrl(uploaded.path);
      toast.success(t('newRun.binaryUploaded', { filename: uploaded.filename }));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBinaryUploading(false);
    }
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
    // Cada provider guarda seu próprio modelo configurado (campo "Modelo"
    // na ConfigPage, ao lado da chave dele) — usa o desse provider
    // independente de qual é o "provider default" global; sem isso, trocar
    // pra um provider não-default aqui sempre sugeria o exemplo hardcoded,
    // ignorando um modelo que a pessoa já tinha configurado pra ele.
    // Continua um campo editável, não trava no sugerido.
    const provider = LLM_PROVIDERS.find((p) => p.id === id);
    const configuredModel = provider ? config?.[provider.defaultModelField] : undefined;
    setLlmModel(configuredModel || provider?.exampleModel || '');
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    if (mode === 'explore') {
      // Confirmação também é exigida pelo backend (run_service.create_run)
      // — checa aqui só pra dar feedback imediato sem round-trip.
      if (!confirmedNonProduction) {
        setFormError(t('newRun.confirmNonProductionRequired'));
        return;
      }
      try {
        const run = await createRun.mutateAsync({
          platform,
          mode: 'explore',
          app_url: platform === 'web' ? appUrl || undefined : undefined,
          binary_url: platform !== 'web' ? binaryUrl || undefined : undefined,
          binary_auth_secret: platform !== 'web' ? binaryAuthSecret || undefined : undefined,
          llm_provider: llmProvider || undefined,
          llm_model: llmModel || undefined,
          max_actions: Number(maxActions) || DEFAULT_EXPLORE_MAX_ACTIONS,
          confirmed_non_production: true,
        });
        toast.success(t('newRun.created'));
        navigate(`/runs/${run.id}`);
      } catch (err) {
        setFormError(err instanceof ApiError ? err.message : String(err));
      }
      return;
    }

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
        mode: 'execute',
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
            <CardTitle>{t('newRun.mode')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select id="run-mode" value={mode} onChange={(e) => setMode(e.target.value as RunMode)}>
              <option value="execute">{t('newRun.modeExecute')}</option>
              <option value="explore">{t('newRun.modeExplore')}</option>
            </Select>
            <p className="text-xs text-muted-foreground">
              {mode === 'execute' ? t('newRun.modeExecuteHelp') : t('newRun.modeExploreHelp')}
            </p>
          </CardContent>
        </Card>

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
                  <div className="flex items-center justify-between">
                    <Label htmlFor="binary-url">{t('newRun.binaryUrl')}</Label>
                    <input
                      ref={binaryFileInputRef}
                      type="file"
                      accept={platform === 'ios' ? '.ipa,.zip' : '.apk,.aab'}
                      aria-label={t('newRun.uploadBinaryFile')}
                      className="hidden"
                      onChange={handleBinaryFileChange}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={binaryUploading}
                      onClick={() => binaryFileInputRef.current?.click()}
                    >
                      <Upload className="h-4 w-4" />
                      {binaryUploading ? t('newRun.binaryUploading') : t('newRun.uploadBinaryFile')}
                    </Button>
                  </div>
                  <Input
                    id="binary-url"
                    type="text"
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

        {mode === 'execute' ? (
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
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>{t('newRun.exploreSettings')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2 sm:max-w-xs">
                <Label htmlFor="max-actions">{t('newRun.maxActions')}</Label>
                <Input
                  id="max-actions"
                  type="text"
                  inputMode="numeric"
                  value={maxActions}
                  onChange={(e) => setMaxActions(e.target.value.replace(/\D/g, ''))}
                />
                <p className="text-xs text-muted-foreground">{t('newRun.maxActionsHelp')}</p>
              </div>
              <label className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={confirmedNonProduction}
                  onChange={(e) => setConfirmedNonProduction(e.target.checked)}
                />
                <span>{t('newRun.confirmNonProduction')}</span>
              </label>
            </CardContent>
          </Card>
        )}

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
