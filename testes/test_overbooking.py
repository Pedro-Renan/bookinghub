"""
BookingHub — testes/test_overbooking.py

Demonstra e valida a solução para o problema de overbooking.

Execução:
    python testes/test_overbooking.py

Pré-requisito:
    - API rodando em http://localhost:8000
    - Voo com available_seats = 1 (script prepara automaticamente)
"""

import threading
import requests
import psycopg2
import os
import time

API_URL    = os.getenv("API_URL", "http://localhost:8000")
DB_URL     = os.getenv("DATABASE_URL",
                        "postgresql://booking:secret@localhost:5432/bookinghub")
N_THREADS  = 50
FLIGHT_ID  = None   # será definido no setup


# ── Setup ─────────────────────────────────────────────────────────────────
def preparar_voo_teste():
    """Cria (ou reutiliza) um voo com exatamente 1 assento disponível."""
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Busca um voo existente com available_seats > 0
    cur.execute("""
        SELECT id FROM flights
        WHERE available_seats > 0
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        cur.close(); conn.close()
        raise RuntimeError("Nenhum voo disponível no banco. Execute o seed primeiro.")

    flight_id = row[0]

    # Garante exactly 1 assento disponível para o teste
    cur.execute("UPDATE flights SET available_seats = 1 WHERE id = %s", (flight_id,))
    # Remove reservas anteriores deste voo para o teste
    cur.execute("""
        DELETE FROM flight_reservations
        WHERE flight_id = %s AND seat_number LIKE 'TEST%'
    """, (flight_id,))
    conn.commit()
    cur.close(); conn.close()
    print(f"  Voo de teste: id={flight_id} | available_seats=1")
    return flight_id


def contar_reservas_confirmadas(flight_id):
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) FROM flight_reservations
        WHERE flight_id = %s AND status != 'cancelled'
    """, (flight_id,))
    count = cur.fetchone()[0]
    cur.close(); conn.close()
    return count


# ── Teste ─────────────────────────────────────────────────────────────────
def executar_teste(flight_id: int, endpoint: str, label: str):
    """Dispara N_THREADS requisições simultâneas e coleta resultados."""
    resultados = {"201": 0, "409": 0, "outros": 0}
    lock = threading.Lock()

    def tentar_reserva(customer_id):
        try:
            r = requests.post(
                f"{API_URL}{endpoint}",
                json={"customer_id": customer_id, "flight_id": flight_id},
                timeout=10,
            )
            with lock:
                key = str(r.status_code) if r.status_code in (201, 409) else "outros"
                resultados[key] += 1
        except Exception as e:
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

    confirmadas_bd = contar_reservas_confirmadas(flight_id)

    print(f"\n  {'─'*50}")
    print(f"  Teste: {label}")
    print(f"  {'─'*50}")
    print(f"  Threads disparadas  : {N_THREADS}")
    print(f"  HTTP 201 (sucesso)  : {resultados['201']}")
    print(f"  HTTP 409 (conflito) : {resultados['409']}")
    print(f"  Outros erros        : {resultados['outros']}")
    print(f"  Reservas no banco   : {confirmadas_bd}")
    print(f"  Duração total       : {duracao:.2f}s")

    overbooking = confirmadas_bd > 1
    if overbooking:
        print(f"  ❌  OVERBOOKING DETECTADO! ({confirmadas_bd} reservas para 1 assento)")
    else:
        print(f"  ✅  Sem overbooking ({confirmadas_bd} reserva confirmada)")

    return not overbooking


# ── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  BookingHub — Teste de Overbooking")
    print("=" * 55)

    flight_id = preparar_voo_teste()

    # Rodada 1: sem controle (simula endpoint sem FOR UPDATE)
    # Para demonstrar o problema, testamos diretamente via banco
    print("\n[1/2] Verificando comportamento com controle de concorrência...")
    ok = executar_teste(flight_id, "/reservas/voo", "POST /reservas/voo (com SELECT FOR UPDATE)")

    # Restaura para novo teste
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("UPDATE flights SET available_seats = 1 WHERE id = %s", (flight_id,))
    cur.execute("UPDATE flight_reservations SET status='cancelled' WHERE flight_id=%s",
                (flight_id,))
    cur.execute("UPDATE flights SET available_seats = 1 WHERE id = %s", (flight_id,))
    conn.commit(); cur.close(); conn.close()

    print("\n[2/2] Segundo teste de confirmação...")
    ok2 = executar_teste(flight_id, "/reservas/voo", "Confirmação — sem overbooking")

    print("\n" + "=" * 55)
    if ok and ok2:
        print("  ✅  RESULTADO FINAL: Overbooking prevenido com sucesso!")
    else:
        print("  ❌  RESULTADO FINAL: Falha no controle de overbooking.")
    print("=" * 55)
