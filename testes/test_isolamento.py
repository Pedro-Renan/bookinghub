"""
BookingHub — testes/test_isolamento.py

Suite de testes que demonstra os três níveis de isolamento do PostgreSQL:
  1. READ COMMITTED  → Non-Repeatable Read
  2. REPEATABLE READ → Non-Repeatable Read eliminado
  3. SERIALIZABLE    → Phantom Read eliminado / serialization_failure

Cada teste abre duas conexões paralelas (T1 e T2) com threading.

Execução:
    python testes/test_isolamento.py
"""

import psycopg2
import threading
import time
import os

DB_URL = os.getenv("DATABASE_URL",
                    "postgresql://booking:secret@localhost:5432/bookinghub")

SEPARATOR = "=" * 60


def nova_conn(isolation_level=None):
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    if isolation_level:
        conn.set_isolation_level(isolation_level)
    return conn


# ── Helpers ───────────────────────────────────────────────────────────────
def buscar_preco_voo(conn, flight_id):
    with conn.cursor() as cur:
        cur.execute("SELECT price FROM flights WHERE id = %s", (flight_id,))
        return float(cur.fetchone()[0])


def atualizar_preco_voo(conn, flight_id, novo_preco):
    with conn.cursor() as cur:
        cur.execute("UPDATE flights SET price = %s WHERE id = %s",
                    (novo_preco, flight_id))
    conn.commit()


def preparar_voo(flight_id=1, preco_inicial=450.00):
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("UPDATE flights SET price = %s WHERE id = %s",
                    (preco_inicial, flight_id))
    conn.close()
    return preco_inicial


# ── TESTE 1: READ COMMITTED — Non-Repeatable Read ─────────────────────────
def teste_read_committed():
    print(f"\n{SEPARATOR}")
    print("TESTE 1 — READ COMMITTED: Non-Repeatable Read")
    print(SEPARATOR)

    FLIGHT_ID     = 1
    PRECO_INICIAL = preparar_voo(FLIGHT_ID, 450.00)
    PRECO_NOVO    = 520.00
    resultado_t2  = {}
    eventos       = {
        "t2_leitura1":  threading.Event(),
        "t1_commit":    threading.Event(),
        "t2_leitura2":  threading.Event(),
    }

    def t1():
        """T1: atualiza o preço e faz commit enquanto T2 está no meio da transação."""
        conn = nova_conn()
        time.sleep(0.3)              # aguarda T2 fazer 1ª leitura
        eventos["t2_leitura1"].wait()
        with conn.cursor() as cur:
            cur.execute("UPDATE flights SET price = %s WHERE id = %s",
                        (PRECO_NOVO, FLIGHT_ID))
        conn.commit()
        print(f"  T1: UPDATE price={PRECO_NOVO} → COMMIT")
        eventos["t1_commit"].set()
        conn.close()

    def t2():
        """T2: lê o preço duas vezes; deve ver valores diferentes (READ COMMITTED)."""
        conn = nova_conn()
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("SELECT price FROM flights WHERE id = %s", (FLIGHT_ID,))
            p1 = float(cur.fetchone()[0])
            resultado_t2["leitura1"] = p1
            print(f"  T2: 1ª leitura → price={p1}")
            eventos["t2_leitura1"].set()

            eventos["t1_commit"].wait()   # espera T1 commitar
            time.sleep(0.1)

            cur.execute("SELECT price FROM flights WHERE id = %s", (FLIGHT_ID,))
            p2 = float(cur.fetchone()[0])
            resultado_t2["leitura2"] = p2
            print(f"  T2: 2ª leitura → price={p2}")
            conn.rollback()
        conn.close()
        eventos["t2_leitura2"].set()

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th2.start(); th1.start()
    th1.join();  th2.join()

    p1 = resultado_t2["leitura1"]
    p2 = resultado_t2["leitura2"]
    non_repeatable = (p1 != p2)
    print(f"\n  Leitura 1: {p1} | Leitura 2: {p2}")
    print(f"  Non-Repeatable Read ocorreu: {'✅ SIM (esperado)' if non_repeatable else '❌ NÃO'}")
    print(f"  Mecanismo: cada statement obtém snapshot do último estado commitado.")
    return non_repeatable


# ── TESTE 2: REPEATABLE READ — Non-Repeatable Read eliminado ──────────────
def teste_repeatable_read():
    print(f"\n{SEPARATOR}")
    print("TESTE 2 — REPEATABLE READ: Non-Repeatable Read eliminado")
    print(SEPARATOR)

    FLIGHT_ID     = 1
    PRECO_INICIAL = preparar_voo(FLIGHT_ID, 450.00)
    PRECO_NOVO    = 520.00
    resultado_t2  = {}
    eventos       = {
        "t2_leitura1": threading.Event(),
        "t1_commit":   threading.Event(),
    }

    def t1():
        conn = nova_conn()
        eventos["t2_leitura1"].wait()
        with conn.cursor() as cur:
            cur.execute("UPDATE flights SET price = %s WHERE id = %s",
                        (PRECO_NOVO, FLIGHT_ID))
        conn.commit()
        print(f"  T1: UPDATE price={PRECO_NOVO} → COMMIT")
        eventos["t1_commit"].set()
        conn.close()

    def t2():
        conn = nova_conn()
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
            cur.execute("SELECT price FROM flights WHERE id = %s", (FLIGHT_ID,))
            p1 = float(cur.fetchone()[0])
            resultado_t2["leitura1"] = p1
            print(f"  T2: 1ª leitura → price={p1}")
            eventos["t2_leitura1"].set()

            eventos["t1_commit"].wait()
            time.sleep(0.1)

            cur.execute("SELECT price FROM flights WHERE id = %s", (FLIGHT_ID,))
            p2 = float(cur.fetchone()[0])
            resultado_t2["leitura2"] = p2
            print(f"  T2: 2ª leitura → price={p2}  ← mesmo snapshot")
            conn.rollback()
        conn.close()

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th2.start(); th1.start()
    th1.join();  th2.join()

    p1 = resultado_t2["leitura1"]
    p2 = resultado_t2["leitura2"]
    eliminado = (p1 == p2)
    print(f"\n  Leitura 1: {p1} | Leitura 2: {p2}")
    print(f"  Non-Repeatable Read eliminado: {'✅ SIM (esperado)' if eliminado else '❌ NÃO'}")
    print(f"  Mecanismo: T2 mantém snapshot do início da transação (MVCC).")
    return eliminado


# ── TESTE 3: SERIALIZABLE — serialization_failure ────────────────────────
def teste_serializable():
    print(f"\n{SEPARATOR}")
    print("TESTE 3 — SERIALIZABLE: Dependência cíclica → serialization_failure")
    print(SEPARATOR)

    FLIGHT_ID = 1
    preparar_voo(FLIGHT_ID, 450.00)

    resultado = {"t2_erro": None, "t2_sqlstate": None}
    eventos   = {
        "t1_leu":    threading.Event(),
        "t2_leu":    threading.Event(),
        "t1_commit": threading.Event(),
    }

    def t1():
        conn = nova_conn()
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            # T1 lê available_seats do voo 1
            cur.execute("SELECT available_seats FROM flights WHERE id = %s",
                        (FLIGHT_ID,))
            val = cur.fetchone()[0]
            print(f"  T1: leu available_seats={val}")
            eventos["t1_leu"].set()
            eventos["t2_leu"].wait()   # aguarda T2 ler

            # T1 atualiza preço com base na leitura de available_seats
            cur.execute("UPDATE flights SET price = price * 1.10 WHERE id = %s",
                        (FLIGHT_ID,))
        try:
            conn.commit()
            print("  T1: COMMIT bem-sucedido")
        except Exception as e:
            conn.rollback()
            print(f"  T1: ROLLBACK — {e}")
        finally:
            eventos["t1_commit"].set()
            conn.close()

    def t2():
        time.sleep(0.1)
        conn = nova_conn()
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            # T2 lê preço do voo 1
            cur.execute("SELECT price FROM flights WHERE id = %s", (FLIGHT_ID,))
            val = cur.fetchone()[0]
            print(f"  T2: leu price={val}")
            eventos["t2_leu"].set()
            eventos["t1_commit"].wait()

            # T2 atualiza available_seats com base na leitura de price
            cur.execute(
                "UPDATE flights SET available_seats = available_seats - 1 "
                "WHERE id = %s", (FLIGHT_ID,))
        try:
            conn.commit()
            print("  T2: COMMIT bem-sucedido")
        except psycopg2.errors.SerializationFailure as e:
            conn.rollback()
            resultado["t2_erro"]     = str(e)
            resultado["t2_sqlstate"] = e.pgcode
            print(f"  T2: ROLLBACK — {e.pgcode}: {str(e)[:80]}")
        except Exception as e:
            conn.rollback()
            resultado["t2_erro"] = str(e)
        finally:
            conn.close()

    th1 = threading.Thread(target=t1)
    th2 = threading.Thread(target=t2)
    th1.start(); th2.start()
    th1.join();  th2.join()

    sqlstate = resultado.get("t2_sqlstate")
    serializado = (sqlstate == "40001")
    print(f"\n  SQLSTATE obtido: {sqlstate}")
    print(f"  Serialização forçada: {'✅ SIM (esperado — 40001)' if serializado else '❌ NÃO'}")
    print(f"  Mecanismo: SSI detectou ciclo rw-antidependency e abortou T2.")
    return serializado


# ── Main ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(SEPARATOR)
    print("  BookingHub — Suite de Testes de Níveis de Isolamento")
    print(SEPARATOR)

    resultados = {
        "READ COMMITTED (Non-Repeatable Read)":    teste_read_committed(),
        "REPEATABLE READ (NRR eliminado)":         teste_repeatable_read(),
        "SERIALIZABLE (serialization_failure)":    teste_serializable(),
    }

    print(f"\n{SEPARATOR}")
    print("  RESUMO DOS TESTES")
    print(SEPARATOR)
    todos_ok = True
    for nome, ok in resultados.items():
        status = "✅ PASSOU" if ok else "❌ FALHOU"
        print(f"  {status}  {nome}")
        if not ok:
            todos_ok = False

    print(SEPARATOR)
    print(f"  {'✅ Todos os testes passaram!' if todos_ok else '❌ Alguns testes falharam.'}")
    print(SEPARATOR)
