import pytest

from src.bdd import (
    BddParseError,
    parse_bdd_script,
    resolve_placeholders,
    scan_placeholders,
    validate_test_data,
)

SIMPLE_SCRIPT = """\
# language: pt
Funcionalidade: Login
  Contexto:
    Dado que estou na página de login

  Cenário: Login válido
    Quando preencho usuário "standard_user"
    E preencho senha "secret_sauce"
    E clico em entrar
    Então vejo a lista de produtos

  Cenário: Login inválido
    Quando preencho usuário "usuario_invalido"
    E clico em entrar
    Então vejo uma mensagem de erro
"""

OUTLINE_SCRIPT = """\
# language: pt
Funcionalidade: Login com massa
  Esquema do Cenário: Login com credenciais variadas
    Quando preencho usuário "<usuario>"
    E clico em entrar
    Então vejo "<resultado>"

    Exemplos:
      | usuario         | resultado |
      | standard_user   | produtos  |
      | locked_out_user | erro      |
"""

PLACEHOLDER_SCRIPT = """\
# language: pt
Funcionalidade: Login com massa de testes
  Cenário: Login válido
    Quando preencho usuário <usuario_valido>
    E preencho senha <senha_valida>
    Então vejo a lista de produtos
"""


def test_parse_applies_background_to_every_scenario():
    scenarios = parse_bdd_script(SIMPLE_SCRIPT)
    assert len(scenarios) == 2
    for scenario in scenarios:
        assert scenario.steps[0].text == "que estou na página de login"
        assert scenario.steps[0].keyword == "Given"


def test_parse_keeps_step_order_and_keywords():
    scenarios = parse_bdd_script(SIMPLE_SCRIPT)
    valid = scenarios[0]
    assert [s.keyword for s in valid.steps] == ["Given", "When", "When", "When", "Then"]
    assert valid.steps[1].text == 'preencho usuário "standard_user"'


def test_parse_expands_scenario_outline_examples():
    scenarios = parse_bdd_script(OUTLINE_SCRIPT)
    assert len(scenarios) == 2
    assert 'preencho usuário "standard_user"' in scenarios[0].steps[0].text
    assert 'vejo "produtos"' in scenarios[0].steps[-1].text
    assert 'preencho usuário "locked_out_user"' in scenarios[1].steps[0].text
    assert 'vejo "erro"' in scenarios[1].steps[-1].text


def test_parse_empty_script_raises():
    with pytest.raises(BddParseError, match="Empty"):
        parse_bdd_script("")


def test_parse_invalid_syntax_raises():
    with pytest.raises(BddParseError, match="Syntax error"):
        parse_bdd_script("isso não é um script Gherkin válido {{{")


def test_parse_script_without_scenarios_raises():
    with pytest.raises(BddParseError, match="No scenario"):
        parse_bdd_script("# language: pt\nFuncionalidade: Vazia\n")


def test_scan_placeholders_finds_all_referenced_names():
    scenarios = parse_bdd_script(PLACEHOLDER_SCRIPT)
    assert scan_placeholders(scenarios) == {"usuario_valido", "senha_valida"}


def test_scan_placeholders_empty_when_no_placeholders():
    scenarios = parse_bdd_script(SIMPLE_SCRIPT)
    assert scan_placeholders(scenarios) == set()


def test_resolve_placeholders_substitutes_values():
    text = resolve_placeholders("preencho usuário <usuario_valido>", {"usuario_valido": "standard_user"})
    assert text == "preencho usuário standard_user"


def test_resolve_placeholders_missing_key_raises():
    with pytest.raises(BddParseError, match="usuario_valido"):
        resolve_placeholders("preencho usuário <usuario_valido>", {})


def test_validate_test_data_passes_when_all_present():
    scenarios = parse_bdd_script(PLACEHOLDER_SCRIPT)
    validate_test_data(scenarios, {"usuario_valido": "standard_user", "senha_valida": "secret_sauce"})


def test_validate_test_data_raises_with_missing_names():
    scenarios = parse_bdd_script(PLACEHOLDER_SCRIPT)
    with pytest.raises(BddParseError, match="usuario_valido"):
        validate_test_data(scenarios, {"senha_valida": "secret_sauce"})
