"""Argus Agent — worker: processa runs `queued` uma de cada vez.

Loop de claim simples sobre a tabela `runs`, sem fila externa (Redis/RQ) —
decisão tomada em PLANO.md: menos uma dependência pra instalar nativamente,
e runs de teste são poucas e longas, não um volume alto que justifique um
broker. Um único worker processa uma run inteira (do grafo até o relatório)
antes de olhar a fila de novo — concorrência entre múltiplos workers fica
para quando `max_concurrent_runs` for implementado (fase de escala)."""
import asyncio
import logging
import signal
import time
from types import FrameType

from src import (  # noqa: F401 — import ajusta PATH/env pro Android SDK (efeito colateral)
    android_env,
    prune,
    store,
)
from src.agent.graph import run_graph

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 2.0
# Prune é manutenção, não algo que precisa reagir em tempo real — rodar a
# cada poll (2s) seria caro à toa (uma query + possível varredura de
# diretórios) sem nenhum benefício, já que a retenção é medida em dias.
PRUNE_INTERVAL_SECONDS = 3600.0

_shutdown_requested = False
# None = "nunca rodou ainda" — dispara o prune imediatamente no primeiro
# giro do loop. Um sentinel numérico (ex.: 0.0) pareceria "no passado", mas
# `time.monotonic()` NÃO é época Unix — é relativo a um ponto arbitrário
# (em geral o boot da máquina), então logo após reiniciar um container/host
# `time.monotonic()` pode ele mesmo valer poucos segundos, menor que
# PRUNE_INTERVAL_SECONDS, e o primeiro prune real só aconteceria depois de
# o relógio monotônico ACUMULAR uma hora — não uma hora após o worker subir.
_last_prune_at: float | None = None


def _request_shutdown(_signum: int, _frame: FrameType | None) -> None:
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("Shutdown solicitado — terminando a run atual antes de sair.")


async def _process_next_queued_run() -> bool:
    """Processa a run `queued` mais antiga, se houver. Retorna True se
    processou alguma (sinal pro loop não dormir antes de checar de novo)."""
    queued_ids = store.list_queued_run_ids()
    if not queued_ids:
        return False

    run_id = queued_ids[0]
    logger.info("Iniciando run %s", run_id)
    try:
        await run_graph(run_id)
        logger.info("Run %s finalizada", run_id)
    except Exception as e:
        # Qualquer exceção não tratada por dentro do grafo (bug, crash do
        # Playwright, etc.) não pode deixar a run presa em "running" pra
        # sempre — mesma preocupação do work_horse_killed_handler do phalanx.
        logger.exception("Run %s falhou de forma não tratada", run_id)
        store.update_run_status(run_id, "error", error=f"Erro interno do worker: {e}", finished_at=True)
    return True


async def _maybe_prune() -> None:
    """Só dispara de fato a cada PRUNE_INTERVAL_SECONDS — a checagem em si
    (comparar um timestamp monotônico) é barata o bastante pra rodar em
    todo giro do loop sem custo real."""
    global _last_prune_at
    now = time.monotonic()
    if _last_prune_at is not None and now - _last_prune_at < PRUNE_INTERVAL_SECONDS:
        return
    _last_prune_at = now
    try:
        await asyncio.to_thread(prune.prune_old_runs)
    except Exception as e:  # nunca deve derrubar o worker — é manutenção, não o caminho crítico
        logger.warning("Falha ao rodar o prune de runs antigas: %s", e)
    try:
        await asyncio.to_thread(prune.prune_stale_uploads)
    except Exception as e:
        logger.warning("Falha ao rodar o prune de uploads órfãos: %s", e)


async def _loop() -> None:
    while not _shutdown_requested:
        processed = await _process_next_queued_run()
        await _maybe_prune()
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def start() -> None:
    """CLI entrypoint: `uv run argus-worker`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)
    logger.info("Argus worker iniciado (poll a cada %ss).", POLL_INTERVAL_SECONDS)
    asyncio.run(_loop())


if __name__ == "__main__":
    start()
