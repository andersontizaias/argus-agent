import pytest

from src.tools.explore_guardrails import is_dangerous_action


@pytest.mark.parametrize("label", [
    'button "Excluir conta"',
    'button "Delete account"',
    'button "Finalizar compra"',
    'button "Confirm payment"',
    'button "Cancelar assinatura"',
    'link "Unsubscribe"',
    'button "Pagar agora"',
    'button "PAY NOW"',  # case-insensitive
    'button "Enviar"',
    'button "Submit"',
])
def test_is_dangerous_action_blocks_known_patterns(label):
    assert is_dangerous_action(label) is True


@pytest.mark.parametrize("label", [
    'link "Produtos"',
    'button "Ver detalhes"',
    'textbox "Username"',
    'link "Sobre nós"',
    'button "Buscar"',  # não bate no denylist (só "enviar"/"send"/"submit")
    'heading "Bem-vindo"',
])
def test_is_dangerous_action_allows_harmless_elements(label):
    assert is_dangerous_action(label) is False
