"""Argus Agent — estimativa de custo por chamada de LLM.

Tabela estática de preço por token (USD por 1 milhão de tokens, input/
output separados) — uma estimativa pra dar visibilidade de custo no
relatório, não um valor de cobrança oficial de cada provider (preços mudam;
essa tabela precisa ser atualizada manualmente, diferente do simulador de
custo do Phalanx, que puxa do LiveBench ao vivo — fora de escopo pro MVP do
Argus). Modelo desconhecido (isso inclui TODO modelo Ollama/custom, que
roda local e genuinamente não tem custo por token) sempre resolve pra $0."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: float
    output_per_million: float


# Preços aproximados em USD por 1M tokens — conferir a página de preço de
# cada provider antes de confiar em decisões de custo importantes.
#
# Entradas Claude conferidas contra platform.claude.com/docs/en/about-claude/
# pricing em 16/ago/2026 (preço de input base, sem cache/batch/fast-mode) —
# cobrem tanto o nome "bonito" que a Anthropic usa na doc quanto a variante
# com hífen (`4-5` em vez de `4.5`) que é o formato mais comum de alias de
# modelo na API; achado ao vivo: um modelo digitado manualmente que não
# bate BYTE A BYTE com uma chave daqui sempre resolve pra $0 (ver
# `estimate_cost_usd` abaixo), então cobrir as duas grafias importa mais
# aqui do que em código que só compara por igualdade uma vez.
_PRICES: dict[str, ModelPrice] = {
    "claude-3-5-haiku-latest": ModelPrice(0.80, 4.00),
    "claude-3-5-sonnet-latest": ModelPrice(3.00, 15.00),
    "claude-haiku-4-5": ModelPrice(1.00, 5.00),
    "claude-haiku-4.5": ModelPrice(1.00, 5.00),
    "claude-haiku-4-5-20251001": ModelPrice(1.00, 5.00),
    "claude-sonnet-4-5": ModelPrice(3.00, 15.00),
    "claude-sonnet-4.5": ModelPrice(3.00, 15.00),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00),
    "claude-sonnet-4.6": ModelPrice(3.00, 15.00),
    "claude-sonnet-5": ModelPrice(2.00, 10.00),
    "claude-opus-4-5": ModelPrice(5.00, 25.00),
    "claude-opus-4.5": ModelPrice(5.00, 25.00),
    "claude-opus-4-6": ModelPrice(5.00, 25.00),
    "claude-opus-4.6": ModelPrice(5.00, 25.00),
    "claude-opus-4-7": ModelPrice(5.00, 25.00),
    "claude-opus-4.7": ModelPrice(5.00, 25.00),
    "claude-opus-4-8": ModelPrice(5.00, 25.00),
    "claude-opus-4.8": ModelPrice(5.00, 25.00),
    "claude-opus-5": ModelPrice(5.00, 25.00),
    "claude-fable-5": ModelPrice(10.00, 50.00),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gemini-2.5-flash": ModelPrice(0.30, 2.50),
    "gemini-2.5-pro": ModelPrice(1.25, 10.00),
    "llama-3.3-70b-versatile": ModelPrice(0.59, 0.79),
}


def estimate_cost_usd(model: str, *, tokens_in: int, tokens_out: int) -> float:
    price = _PRICES.get(model)
    if price is None:
        return 0.0
    return (tokens_in / 1_000_000) * price.input_per_million + (tokens_out / 1_000_000) * price.output_per_million
