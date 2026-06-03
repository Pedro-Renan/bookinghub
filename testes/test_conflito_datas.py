"""
BookingHub — testes/test_conflito_datas.py

Demonstra a solução para conflito de datas em reservas de hotel.
30 threads tentam reservar o mesmo quarto para o mesmo período.

Execução:
    python testes/test_conflito_datas.py
"""

import threading
import requests
import psycopg2
import os
import time
from datetime import date, timedelta

API_URL = os.getenv("API_URL", "http://localhost:8000")
DB_URL  = os.getenv("DATABASE_URL",
                     "postgresql://booking:secret@localhost:5432/bookinghub")
N_THREADS = 30


def preparar_quarto_teste():
    """Busca um quarto livre e cancela reservas existentes no período de teste."""
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    check_in  = date.today() + timedelta(days=30)
    check_out = check_in + timedelta(days=7)

    # Busca quarto disponível
    cur.execute("""
        SELECT r.id FROM rooms r
        WHERE r.id NOT IN (
            SELECT hr.room_id FROM hotel_reservations hr
            WHERE hr.status != 'cancelled'
              AND hr.check_in  < %s
              AND hr.check_out > %s
        )
        LIMIT 1
    """, (check_out, check_in))
    row = cur.fetchone()
    if not row:
        # Cancela reservas para liberar um quarto
        cur.execute("""
            UPDATE hotel_reservations SET status = 'cancelled'
            WHERE room_id = (SELECT id FROM rooms LIMIT 1)
              AND check_in < %s AND check_out > %s
        """, (check_out, check_in))
        conn.commit()
        cur.execute("SELECT id FROM rooms LIMIT 1")
        row = cur.fetchone()

    room_id = row[0]
    conn.commit(); cur.close(); conn.close()
    print(f"  Quarto de teste: id={room_id}")
    print(f"  Período        : {check_in} → {check_out}")
    return room_id, check_in, check_out


def contar_reservas_quarto(room_id, check_in, check_out):
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM hotel_reservations
        WHERE room_id    = %s
          AND status    != 'cancelled'
          AND check_in   < %s
          AND check_out  > %s
    """, (room_id, check_out, check_in))
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return count


def executar_teste(room_id, check_in, check_out):
    resultados = {"201": 0, "409": 0, "outros": 0}
    lock = threading.Lock()

    def tentar_reserva(customer_id):
        try:
            r = requests.post(
                f"{API_URL}/reservas/hotel",
                json={
                    "customer_id": customer_id,
                    "room_id":     room_id,
                    "check_in":    str(check_in),
                    "check_out":   str(check_out),
                },
                timeout=10,
            )
            with lock:
                key = str(r.status_code) if r.status_code in (201, 409) else "outros"
                resultados[key] += 1
        except Exception:
            with lock:
                resultados["outros"] += 1

    threads = [
        threading.Thread(target=tentar_reserva, args=(i + 1,))
        for i in range(N_THREADS)
    ]

    inicio = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    duracao = time.time() - inicio

    confirmadas = contar_reservas_quarto(room_id, check_in, check_out)

    print(f"\n  {'─'*50}")
    print(f"  Threads disparadas  : {N_THREADS}")
    print(f"  HTTP 201 (sucesso)  : {resultados['201']}")
    print(f"  HTTP 409 (conflito) : {resultados['409']}")
    print(f"  Outros              : {resultados['outros']}")
    print(f"  Reservas no banco   : {confirmadas}")
    print(f"  Duração total       : {duracao:.2f}s")

    if confirmadas > 1:
        print(f"  ❌  CONFLITO DE DATAS! ({confirmadas} reservas para o mesmo quarto/período)")
        return False
    else:
        print(f"  ✅  Sem conflito de datas ({confirmadas} reserva confirmada)")
        return True


if __name__ == "__main__":
    print("=" * 55)
    print("  BookingHub — Teste de Conflito de Datas (Hotel)")
    print("=" * 55)

    room_id, check_in, check_out = preparar_quarto_teste()
    ok = executar_teste(room_id, check_in, check_out)

    print("\n" + "=" * 55)
    resultado = "✅  APROVADO" if ok else "❌  REPROVADO"
    print(f"  {resultado}: Controle de conflito de datas")
    print("=" * 55)
