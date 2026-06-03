"""
BookingHub — api/utils/retry.py
Retry com backoff exponencial para falhas de serialização (SQLSTATE 40001).
"""

import time
import random
import psycopg2


def executar_com_retry(fn, max_tentativas: int = 3):
    """
    Executa fn() re-tentando até max_tentativas vezes em caso de
    psycopg2.errors.SerializationFailure (SQLSTATE 40001).

    Backoff exponencial com jitter:
        tentativa 0 → espera ~100ms
        tentativa 1 → espera ~200ms
        tentativa 2 → lança a exceção (último retry esgotado)
    """
    for tentativa in range(max_tentativas):
        try:
            return fn()
        except psycopg2.errors.SerializationFailure:
            if tentativa == max_tentativas - 1:
                raise   # re-raise → endpoint retorna HTTP 409
            espera = (2 ** tentativa) * 0.1 + random.uniform(0, 0.05)
            time.sleep(espera)
