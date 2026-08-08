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


# Preços aproximados em USD por 1M tokens — snapshot de ago/2026, conferir
# a página de preço de cada provider antes de confiar em decisões de custo
# importantes.
_PRICES: dict[str, ModelPrice] = {
    "claude-3-5-haiku-latest": ModelPrice(0.80, 4.00),
    "claude-3-5-sonnet-latest": ModelPrice(3.00, 15.00),
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
