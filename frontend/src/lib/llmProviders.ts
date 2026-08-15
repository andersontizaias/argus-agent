import type { ProjectConfig } from '@/types/api';

// Lista declarativa dos providers LLM suportados — mesmo padrão do
// ConfigPage do phalanx-agents: adicionar um provider novo é uma linha
// aqui (o backend já resolve via src/llm_providers.py). Compartilhada entre
// ConfigPage (onde as chaves/URLs são cadastradas) e NewRunPage (onde só se
// escolhe, por dropdown, qual provider já configurado usar).
export interface LlmProviderAdvancedField {
  field: keyof ProjectConfig;
  label: string;
  type?: 'text' | 'password';
  /** Sem isso, o campo é opcional dentro do modo avançado (ex.: session
   * token — só necessário pra credenciais temporárias/STS). */
  required?: boolean;
}

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
  // ProviderInfo.example_model em src/llm_providers.py. Usado como
  // placeholder do campo de modelo abaixo quando o provider ainda não tem
  // um configurado.
  exampleModel: string;
  // Modelo default DESSE provider — um campo por provider (não um único
  // global), espelha `default_model_setting_name` em src/llm_providers.py.
  // Cadastrado junto com a chave/URL na ConfigPage; usado como sugestão ao
  // escolher esse provider na Nova Execução.
  defaultModelField: keyof ProjectConfig;
  // Campos escondidos atrás de um botão "Mostrar avançado" — hoje só o
  // Bedrock usa (modo SigV4 alternativo à API key). Genérico o bastante
  // pra outro provider futuro com o mesmo padrão "modo simples + avançado".
  advancedFields?: LlmProviderAdvancedField[];
}

export const LLM_PROVIDERS: LlmProviderMeta[] = [
  {
    id: 'anthropic', label: 'Anthropic', apiKeyField: 'anthropic_api_key', needsApiKey: true,
    exampleModel: 'claude-3-5-haiku-latest', defaultModelField: 'anthropic_default_model',
  },
  {
    id: 'openai', label: 'OpenAI', apiKeyField: 'openai_api_key', needsApiKey: true,
    exampleModel: 'gpt-4o-mini', defaultModelField: 'openai_default_model',
  },
  {
    id: 'google_genai', label: 'Google Gemini', apiKeyField: 'gemini_api_key', needsApiKey: true,
    exampleModel: 'gemini-2.5-flash', defaultModelField: 'gemini_default_model',
  },
  {
    id: 'groq', label: 'Groq', apiKeyField: 'groq_api_key', needsApiKey: true,
    exampleModel: 'llama-3.3-70b-versatile', defaultModelField: 'groq_default_model',
  },
  {
    id: 'ollama', label: 'Ollama (local ou remoto)', apiKeyField: 'ollama_api_key', needsApiKey: false,
    needsBaseUrl: true, baseUrlField: 'ollama_base_url',
    baseUrlPlaceholder: 'http://localhost:11434 ou http://<host-remoto>:11434',
    helpText: 'A chave de API é opcional — só necessária se o servidor Ollama estiver atrás de um proxy com autenticação (Bearer token).',
    timeoutField: 'ollama_timeout_seconds',
    exampleModel: 'qwen2.5:14b', defaultModelField: 'ollama_default_model',
  },
  {
    id: 'custom', label: 'Custom (compatível com OpenAI)', apiKeyField: 'custom_llm_api_key', needsApiKey: true,
    needsBaseUrl: true, baseUrlField: 'custom_llm_base_url', exampleModel: '',
    defaultModelField: 'custom_llm_default_model',
  },
  {
    id: 'bedrock', label: 'AWS Bedrock', apiKeyField: 'bedrock_api_key', needsApiKey: false,
    needsBaseUrl: true, baseUrlField: 'bedrock_region', baseUrlPlaceholder: 'us-east-1 (região AWS)',
    helpText: 'API key do Bedrock (curta ou longa duração). Prefere credenciais IAM clássicas (access key/secret/session token)? Use os campos avançados abaixo.',
    advancedFields: [
      { field: 'bedrock_access_key_id', label: 'AWS Access Key ID', type: 'text', required: true },
      { field: 'bedrock_secret_access_key', label: 'AWS Secret Access Key', type: 'password', required: true },
      { field: 'bedrock_session_token', label: 'AWS Session Token (opcional — só para credenciais temporárias/STS)', type: 'password' },
    ],
    exampleModel: 'us.anthropic.claude-3-5-haiku-20241022-v1:0', defaultModelField: 'bedrock_default_model',
  },
];

/** Espelha `is_provider_configured` de src/llm_providers.py — mesma regra,
 * calculada no cliente porque `GET /api/config` já devolve tudo que ela
 * precisa (chaves mascaradas mas não-vazias, URLs) sem uma rota dedicada. */
export function isProviderConfigured(provider: LlmProviderMeta, config: Partial<ProjectConfig> | undefined): boolean {
  if (!config) return false;
  if (provider.needsBaseUrl && provider.baseUrlField && !config[provider.baseUrlField]) return false;

  const hasApiKey = !!config[provider.apiKeyField];
  if (provider.advancedFields) {
    // Modo "simples + avançado" (hoje só o Bedrock): API key OU todos os
    // advancedFields obrigatórios presentes — mesma lógica OR do backend
    // (is_provider_configured em src/llm_providers.py).
    const requiredAdvanced = provider.advancedFields.filter((f) => f.required);
    const hasAdvanced = requiredAdvanced.length > 0 && requiredAdvanced.every((f) => !!config[f.field]);
    return hasApiKey || hasAdvanced;
  }
  if (provider.needsApiKey && !hasApiKey) return false;
  return true;
}
