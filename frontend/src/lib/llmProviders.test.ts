import { describe, expect, it } from 'vitest';
import { LLM_PROVIDERS, isProviderConfigured } from './llmProviders';
import type { ProjectConfig } from '@/types/api';

const anthropic = LLM_PROVIDERS.find((p) => p.id === 'anthropic')!;
const ollama = LLM_PROVIDERS.find((p) => p.id === 'ollama')!;
const bedrock = LLM_PROVIDERS.find((p) => p.id === 'bedrock')!;

describe('isProviderConfigured', () => {
  it('returns false when there is no config yet', () => {
    expect(isProviderConfigured(anthropic, undefined)).toBe(false);
  });

  it('a provider that needs an api key is unconfigured without one', () => {
    expect(isProviderConfigured(anthropic, {})).toBe(false);
  });

  it('a provider that needs an api key is configured once it has one', () => {
    expect(isProviderConfigured(anthropic, { anthropic_api_key: 'sk-ant-****' })).toBe(true);
  });

  it('a provider that needs a base URL is unconfigured without one, even with an api key', () => {
    expect(isProviderConfigured(ollama, { ollama_api_key: 'token' })).toBe(false);
  });

  it('a provider that needs a base URL is configured once it has one (api key optional)', () => {
    expect(isProviderConfigured(ollama, { ollama_base_url: 'http://localhost:11434' })).toBe(true);
  });

  // --- Bedrock: modo "API key OU SigV4 avançado" ---

  it('bedrock is unconfigured without a region, even with an api key', () => {
    expect(isProviderConfigured(bedrock, { bedrock_api_key: 'token' })).toBe(false);
  });

  it('bedrock is configured with just the api key + region', () => {
    const config: Partial<ProjectConfig> = { bedrock_region: 'us-east-1', bedrock_api_key: 'token' };
    expect(isProviderConfigured(bedrock, config)).toBe(true);
  });

  it('bedrock is configured with the sigv4 advanced fields + region, no api key needed', () => {
    const config: Partial<ProjectConfig> = {
      bedrock_region: 'us-east-1',
      bedrock_access_key_id: 'AKIAEXAMPLE',
      bedrock_secret_access_key: 'secret-value',
    };
    expect(isProviderConfigured(bedrock, config)).toBe(true);
  });

  it('bedrock is unconfigured with only one of the two required sigv4 fields', () => {
    const config: Partial<ProjectConfig> = { bedrock_region: 'us-east-1', bedrock_access_key_id: 'AKIAEXAMPLE' };
    expect(isProviderConfigured(bedrock, config)).toBe(false);
  });

  it('bedrock is unconfigured with region but neither auth mode filled in', () => {
    expect(isProviderConfigured(bedrock, { bedrock_region: 'us-east-1' })).toBe(false);
  });
});
