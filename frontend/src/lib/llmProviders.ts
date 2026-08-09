import type { ProjectConfig } from '@/types/api';

// Lista declarativa dos providers LLM suportados — mesmo padrão do
// ConfigPage do phalanx-agents: adicionar um provider novo é uma linha
// aqui (o backend já resolve via src/llm_providers.py). Compartilhada entre
// ConfigPage (onde as chaves/URLs são cadastradas) e NewRunPage (onde só se
// escolhe, por dropdown, qual provider já configurado usar).
export interface LlmProviderMeta {
  id: string;
  label: string;
  apiKeyField: keyof ProjectConfig;
  needsApiKey: boolean;
  needsBaseUrl?: boolean;
  baseUrlField?: keyof ProjectConfig;
  baseUrlPlaceholder?: string;
  helpText?: string;
  timeoutField?: keyof ProjectConfig;
  // Sem prefixo do provider — só o nome do modelo, espelha
  // ProviderInfo.example_model em src/llm_providers.py. Usado como sugestão
  // ao escolher o provider na Nova Execução (não existe, hoje, uma lista de
  // modelos "cadastrados" por provider — só um default global).
  exampleModel: string;
}

export const LLM_PROVIDERS: LlmProviderMeta[] = [
  { id: 'anthropic', label: 'Anthropic', apiKeyField: 'anthropic_api_key', needsApiKey: true, exampleModel: 'claude-3-5-haiku-latest' },
  { id: 'openai', label: 'OpenAI', apiKeyField: 'openai_api_key', needsApiKey: true, exampleModel: 'gpt-4o-mini' },
  { id: 'google_genai', label: 'Google Gemini', apiKeyField: 'gemini_api_key', needsApiKey: true, exampleModel: 'gemini-2.5-flash' },
  { id: 'groq', label: 'Groq', apiKeyField: 'groq_api_key', needsApiKey: true, exampleModel: 'llama-3.3-70b-versatile' },
  {
    id: 'ollama', label: 'Ollama (local ou remoto)', apiKeyField: 'ollama_api_key', needsApiKey: false,
    needsBaseUrl: true, baseUrlField: 'ollama_base_url',
    baseUrlPlaceholder: 'http://localhost:11434 ou http://<host-remoto>:11434',
    helpText: 'A chave de API é opcional — só necessária se o servidor Ollama estiver atrás de um proxy com autenticação (Bearer token).',
    timeoutField: 'ollama_timeout_seconds',
    exampleModel: 'qwen2.5:14b',
  },
  {
    id: 'custom', label: 'Custom (compatível com OpenAI)', apiKeyField: 'custom_llm_api_key', needsApiKey: true,
    needsBaseUrl: true, baseUrlField: 'custom_llm_base_url', exampleModel: '',
  },
];

/** Espelha `is_provider_configured` de src/llm_providers.py — mesma regra,
 * calculada no cliente porque `GET /api/config` já devolve tudo que ela
 * precisa (chaves mascaradas mas não-vazias, URLs) sem uma rota dedicada. */
export function isProviderConfigured(provider: LlmProviderMeta, config: Partial<ProjectConfig> | undefined): boolean {
  if (!config) return false;
  if (provider.needsApiKey && !config[provider.apiKeyField]) return false;
  if (provider.needsBaseUrl && provider.baseUrlField && !config[provider.baseUrlField]) return false;
  return true;
}
