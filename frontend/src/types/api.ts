export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  checks: HealthCheck[];
}

export interface ProjectConfig {
  anthropic_api_key: string;
  openai_api_key: string;
  gemini_api_key: string;
  groq_api_key: string;
  ollama_api_key: string;
  ollama_base_url: string;
  ollama_timeout_seconds: string;
  custom_llm_api_key: string;
  custom_llm_base_url: string;
  default_llm_provider: string;
  default_llm_model: string;
}

export interface LlmProviderTestResult {
  ok?: boolean;
  provider?: string;
  model?: string;
  error?: string;
}
