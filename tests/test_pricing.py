from src.pricing import estimate_cost_usd


def test_estimate_cost_usd_known_model():
    cost = estimate_cost_usd("gpt-4o-mini", tokens_in=1_000_000, tokens_out=1_000_000)
    assert cost == 0.15 + 0.60


def test_estimate_cost_usd_zero_tokens_is_free():
    assert estimate_cost_usd("gpt-4o-mini", tokens_in=0, tokens_out=0) == 0.0


def test_estimate_cost_usd_unknown_model_is_free():
    # Cobre Ollama/custom (rodam local, genuinamente sem custo por token) e
    # qualquer modelo cloud fora da tabela estática.
    assert estimate_cost_usd("qwen3-coder:30b", tokens_in=5000, tokens_out=2000) == 0.0
    assert estimate_cost_usd("", tokens_in=100, tokens_out=100) == 0.0


def test_estimate_cost_usd_covers_both_dash_and_dot_spellings_of_current_claude_models():
    # Regressão (achada ao vivo): uma run com "claude-haiku-4-5" (o modelo
    # que o usuário tinha configurado) resolvia pra custo $0 — a tabela só
    # tinha os aliases antigos ("-latest"), não a geração atual. O lookup é
    # por igualdade exata de string, então as duas grafias comuns (hífen e
    # ponto) precisam estar cobertas, não só uma.
    assert estimate_cost_usd("claude-haiku-4-5", tokens_in=1_000_000, tokens_out=1_000_000) == 1.00 + 5.00
    assert estimate_cost_usd("claude-haiku-4.5", tokens_in=1_000_000, tokens_out=1_000_000) == 1.00 + 5.00
    assert estimate_cost_usd("claude-sonnet-4-5", tokens_in=1_000_000, tokens_out=1_000_000) == 3.00 + 15.00
    assert estimate_cost_usd("claude-sonnet-4.5", tokens_in=1_000_000, tokens_out=1_000_000) == 3.00 + 15.00
    assert estimate_cost_usd("claude-opus-5", tokens_in=1_000_000, tokens_out=1_000_000) == 5.00 + 25.00
    assert estimate_cost_usd("claude-sonnet-5", tokens_in=1_000_000, tokens_out=1_000_000) == 2.00 + 10.00
