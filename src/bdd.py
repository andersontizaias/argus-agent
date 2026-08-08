"""Argus Agent — parser de BDD (Gherkin), 100% determinístico.

Usa o parser oficial da Cucumber (`gherkin-official`) para transformar o
script em cenários já expandidos: `Esquema do Cenário`/`Scenario Outline` +
`Exemplos`/`Examples` viram um cenário por linha da tabela, e os passos do
`Contexto`/`Background` são aplicados a cada cenário automaticamente. Nenhum
LLM entra nesse caminho — evita alucinação estrutural e economiza tokens; o
LLM só entra na execução de cada passo já resolvido (ver src/agent/executor.py).

O parser da Cucumber detecta o idioma do script pelo comentário `# language:
pt` (ou por palavras-chave nativas) e normaliza cada passo num de três tipos
(`Context`/`Action`/`Outcome`, herdado por `E`/`And`/`Mas`/`But`) —
independente do idioma do script, o que elimina qualquer acoplamento com
tradução de keywords."""
import re
from dataclasses import dataclass, field
from typing import cast

from gherkin.parser import Parser
from gherkin.pickles.compiler import Compiler, GherkinDocumentWithURI

_STEP_TYPE_TO_KEYWORD = {
    "Context": "Given",
    "Action": "When",
    "Outcome": "Then",
    "Unknown": "And",
}

_PLACEHOLDER_RE = re.compile(r"<([^<>]+)>")


class BddParseError(ValueError):
    """Script BDD inválido — erro de sintaxe Gherkin ou massa de testes incompleta."""


@dataclass(frozen=True)
class ParsedStep:
    keyword: str
    text: str


@dataclass(frozen=True)
class ParsedScenario:
    name: str
    steps: list[ParsedStep] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def parse_bdd_script(source: str) -> list[ParsedScenario]:
    """Faz o parsing completo: Background aplicado, Scenario Outline expandido.
    Levanta BddParseError com uma mensagem legível em caso de sintaxe inválida
    ou script sem nenhum cenário."""
    if not source or not source.strip():
        raise BddParseError("Script BDD vazio.")

    try:
        document = Parser().parse(source)
    except Exception as e:  # gherkin levanta CompositeParserException/ParserException
        raise BddParseError(f"Erro de sintaxe no script BDD: {e}") from e

    document_with_uri = cast(GherkinDocumentWithURI, {**document, "uri": "run.feature"})
    pickles = Compiler().compile(document_with_uri)
    if not pickles:
        raise BddParseError("Nenhum cenário encontrado no script BDD.")

    scenarios = []
    for pickle in pickles:
        steps = [
            ParsedStep(
                keyword=_STEP_TYPE_TO_KEYWORD.get(step.get("type", "Unknown"), "And"),
                text=step["text"],
            )
            for step in pickle["steps"]
        ]
        scenarios.append(ParsedScenario(
            name=pickle["name"],
            steps=steps,
            tags=[t["name"] for t in pickle.get("tags", [])],
        ))
    return scenarios


def scan_placeholders(scenarios: list[ParsedScenario]) -> set[str]:
    """Coleta todo `<nome>` referenciado no texto dos passos — são chaves que
    devem existir na massa de testes (JSON) da run. Scenario Outline já foi
    resolvido pelo parser antes disso, então um `<nome>` remanescente aqui é
    sempre uma referência à massa de testes, nunca mais um placeholder de
    Examples."""
    names: set[str] = set()
    for scenario in scenarios:
        for step in scenario.steps:
            names.update(_PLACEHOLDER_RE.findall(step.text))
    return names


def resolve_placeholders(text: str, test_data: dict[str, str]) -> str:
    """Substitui `<nome>` pelo valor correspondente em `test_data`. Usado só
    em tempo de execução (dentro do prompt enviado ao LLM) — o texto
    persistido em `steps.text` mantém o placeholder original, nunca o valor
    resolvido (que pode ser uma credencial), então relatórios/eventos nunca
    vazam a massa de testes."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in test_data:
            raise BddParseError(f"Placeholder <{key}> não encontrado na massa de testes.")
        return str(test_data[key])

    return _PLACEHOLDER_RE.sub(_replace, text)


def validate_test_data(scenarios: list[ParsedScenario], test_data: dict[str, str]) -> None:
    """Levanta BddParseError se algum `<nome>` referenciado no BDD não tiver
    valor correspondente na massa de testes — falha cedo, antes de provisionar
    qualquer navegador/emulador."""
    missing = sorted(scan_placeholders(scenarios) - test_data.keys())
    if missing:
        raise BddParseError(
            "Placeholders sem valor na massa de testes: " + ", ".join(f"<{m}>" for m in missing)
        )
