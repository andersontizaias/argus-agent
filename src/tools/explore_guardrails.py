"""Argus Agent — guardrails do modo "explore" (agente navega sozinho, sem
passo determinado por um humano): bloqueio EM CÓDIGO de ações cujo nome/role
sugere uma consequência real (compra, exclusão, cancelamento, envio) — não
confia só em instrução de prompt, que pode ser seguida de forma
inconsistente. Compartilhado por `build_explore_web_tools`
(src/tools/web.py) e `build_explore_mobile_tools` (src/tools/mobile.py)."""

# pt + en — nome/role do elemento-alvo (já disponível no último snapshot,
# via WebSession.element_label/MobileSession.element_label) comparado
# contra essa lista antes de clicar/tocar. Pende pro lado de bloquear
# demais de propósito: um falso positivo custa um elemento não-explorado; um
# falso negativo pode custar uma ação real irreversível (compra de verdade,
# conta apagada, e-mail de verdade enviado). Documentado como limitação
# conhecida — substring simples, não entende contexto (ex.: "buscar"/
# "enviar" num campo de busca inofensivo pode ser bloqueado à toa).
DANGEROUS_ACTION_KEYWORDS = (
    "excluir", "deletar", "apagar conta", "cancelar assinatura", "cancelar plano",
    "finalizar compra", "confirmar pagamento", "confirmar pedido", "pagar agora",
    "enviar", "assinar", "publicar", "sacar", "transferir",
    "delete", "remove account", "close account", "unsubscribe", "cancel subscription",
    "checkout", "confirm order", "confirm payment", "place order", "pay now",
    "send", "submit", "publish", "withdraw", "transfer",
)


def is_dangerous_action(element_label: str) -> bool:
    """`element_label` é o `'{role} "{name}"'` já resolvido pelo chamador —
    substring simples (case-insensitive) contra o denylist acima."""
    normalized = element_label.strip().lower()
    return any(keyword in normalized for keyword in DANGEROUS_ACTION_KEYWORDS)


DANGEROUS_ACTION_REFUSAL = (
    "Ação bloqueada por segurança no modo exploração — o elemento-alvo parece "
    "iniciar uma ação com efeito real (compra, exclusão, cancelamento, envio). "
    "Escolha outro elemento."
)
