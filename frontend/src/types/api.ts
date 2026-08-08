export interface HealthCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
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
  retention_days: string;
}

export interface LlmProviderTestResult {
  ok?: boolean;
  provider?: string;
  model?: string;
  error?: string;
}

export type RunPlatform = 'web' | 'android' | 'ios';
export type RunStatus = 'queued' | 'provisioning' | 'running' | 'passed' | 'failed' | 'error' | 'canceled';
export type ScenarioStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
export type StepStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

export const TERMINAL_RUN_STATUSES: RunStatus[] = ['passed', 'failed', 'error', 'canceled'];

export interface EvidenceRef {
  id: string;
  type: string;
  label: string;
}

export interface Step {
  id: string;
  position: number;
  keyword: string;
  text: string;
  status: StepStatus;
  error: string | null;
  attempts: number;
  duration_ms: number | null;
  evidences: EvidenceRef[];
}

export interface Scenario {
  id: string;
  position: number;
  name: string;
  tags: string[];
  status: ScenarioStatus;
  failure_reason: string | null;
  started_at: string | null;
  finished_at: string | null;
  steps: Step[];
}

export interface RunSummary {
  id: string;
  platform: RunPlatform;
  app_url: string | null;
  binary_url: string | null;
  status: RunStatus;
  error: string | null;
  cancel_requested: boolean;
  llm_provider: string | null;
  llm_model: string | null;
  scenarios_total: number;
  scenarios_passed: number;
  scenarios_failed: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunDetail extends RunSummary {
  bdd_script: string;
  test_data_keys: string[];
  scenarios: Scenario[];
}

export interface RunsPage {
  runs: RunSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunCreateRequest {
  platform: RunPlatform;
  app_url?: string;
  binary_url?: string;
  binary_auth_secret?: string;
  bdd_script: string;
  test_data?: Record<string, string>;
  llm_provider?: string;
  llm_model?: string;
}

export interface ApiKeySummary {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked: boolean;
}

export interface ApiKeyCreated extends ApiKeySummary {
  key: string;
}
