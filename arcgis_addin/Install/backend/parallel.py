# -*- coding: utf-8 -*-
"""
Paralelismo seguro para o download de tiles - Python 3.

  * imap_bounded: como pool.map, mas com no maximo `workers * PENDING_PER_WORKER` tarefas em
    andamento. Os resultados nunca se acumulam na memoria (antes, 100 mil tiles eram submetidos
    de uma vez e, se a gravacao atrasasse, as respostas ficavam todas em RAM).
  * default_workers: threads de rede. Medido na rede da SEMA (Google Earth, 225 tiles):
    8 = 32 tiles/s, 16 = 65, 32 = 112, 48 = 141, 64 = 158. O ganho satura perto de 48.
  * default_cores: nucleos para o GDAL (piramides, reprojecao), deixando folga para o ArcMap.
"""
import itertools
import os
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

MIN_WORKERS, MAX_WORKERS = 4, 64
PENDING_PER_WORKER = 4


def cpu_count():
    return os.cpu_count() or 4


def default_workers():
    return max(8, min(48, 4 * cpu_count()))


def clamp_workers(value):
    """Valor pedido (0/None = automatico) limitado a 4..64: mais que isso so provoca HTTP 429."""
    try:
        value = int(value or 0)
    except (TypeError, ValueError):
        value = 0
    return default_workers() if value <= 0 else max(MIN_WORKERS, min(MAX_WORKERS, value))


def default_cores():
    return max(1, min(16, cpu_count() - 2))


def gdal_threads():
    """Valor para GDAL_NUM_THREADS / NUM_THREADS (nunca todos os nucleos: o ArcMap fica responsivo)."""
    return str(default_cores())


def imap_bounded(fn, items, workers, pending_per_worker=PENDING_PER_WORKER):
    """Gera fn(item) na ordem de conclusao, com memoria limitada. Uma excecao em fn e propagada."""
    workers = max(1, int(workers))
    limit = workers * max(1, int(pending_per_worker))
    it = iter(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = set(pool.submit(fn, x) for x in itertools.islice(it, limit))
        try:
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for fut in done:
                    result = fut.result()
                    nxt = next(it, _END)
                    if nxt is not _END:
                        pending.add(pool.submit(fn, nxt))
                    yield result
        finally:
            for fut in pending:      # erro ou consumidor abandonou: nao iniciar o resto
                fut.cancel()


_END = object()
