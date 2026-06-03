"""
BookingHub — api/routers/pagamentos.py
Endpoints de pagamento, clientes e relatórios.
"""

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from datetime import date
from api.utils.db import get_db

router = APIRouter(tags=["Pagamentos e Clientes"])


# ── Schemas ───────────────────────────────────────────────────────────────
class PagamentoPayload(BaseModel):
    reservation_type: str   # 'flight' | 'hotel'
    reservation_id:   int
    payment_method:   str = "credit_card"


# ── Pagamentos ────────────────────────────────────────────────────────────
@router.post("/pagamentos", status_code=201)
def registrar_pagamento(payload: PagamentoPayload, db=Depends(get_db)):
    """
    POST /pagamentos
    Registra pagamento e confirma a reserva associada.
    Operação atômica: pagamento + atualização de status em uma transação.
    """
    if payload.reservation_type not in ("flight", "hotel"):
        raise HTTPException(400, "reservation_type deve ser 'flight' ou 'hotel'")

    METODOS_VALIDOS = ("credit_card", "debit_card", "pix", "bank_transfer")
    if payload.payment_method not in METODOS_VALIDOS:
        raise HTTPException(400, f"Método inválido. Use: {METODOS_VALIDOS}")

    with db:
        with db.cursor() as cur:
            # Busca a reserva e bloqueia
            if payload.reservation_type == "flight":
                cur.execute("""
                    SELECT id, status, flight_id
                    FROM flight_reservations
                    WHERE id = %s FOR UPDATE
                """, (payload.reservation_id,))
                res = cur.fetchone()
                if not res:
                    raise HTTPException(404, "Reserva de voo não encontrada")
                if res["status"] != "pending":
                    raise HTTPException(409,
                        f"Reserva com status '{res['status']}' não pode ser paga")
                # Obtém valor
                cur.execute("SELECT price FROM flights WHERE id = %s",
                            (res["flight_id"],))
                amount = float(cur.fetchone()["price"])
                # Confirma reserva
                cur.execute("""
                    UPDATE flight_reservations
                    SET status = 'confirmed', updated_at = NOW()
                    WHERE id = %s
                """, (payload.reservation_id,))

            else:  # hotel
                cur.execute("""
                    SELECT id, status, total_price
                    FROM hotel_reservations
                    WHERE id = %s FOR UPDATE
                """, (payload.reservation_id,))
                res = cur.fetchone()
                if not res:
                    raise HTTPException(404, "Reserva de hotel não encontrada")
                if res["status"] != "pending":
                    raise HTTPException(409,
                        f"Reserva com status '{res['status']}' não pode ser paga")
                amount = float(res["total_price"])
                cur.execute("""
                    UPDATE hotel_reservations
                    SET status = 'confirmed'
                    WHERE id = %s
                """, (payload.reservation_id,))

            # Registra pagamento
            cur.execute("""
                INSERT INTO payments
                    (reservation_type, reservation_id, amount, status, payment_method)
                VALUES (%s, %s, %s, 'confirmed', %s)
                RETURNING id
            """, (payload.reservation_type, payload.reservation_id,
                  amount, payload.payment_method))
            pay_id = cur.fetchone()["id"]

    return {
        "pagamento_id":    pay_id,
        "reservation_type": payload.reservation_type,
        "reservation_id":  payload.reservation_id,
        "amount":          amount,
        "status":          "confirmed",
        "payment_method":  payload.payment_method,
    }


# ── Clientes ──────────────────────────────────────────────────────────────
@router.get("/clientes/{customer_id}/reservas")
def historico_cliente(customer_id: int, db=Depends(get_db)):
    """
    GET /clientes/{id}/reservas
    Retorna histórico completo de reservas (voos + hotéis) com pagamentos.
    Consulta C4 do trabalho — usa UNION ALL.
    Índices: idx_fr_customer, idx_hr_customer, idx_pay_res.
    """
    with db.cursor() as cur:
        cur.execute("SELECT id, name, email FROM customers WHERE id = %s",
                    (customer_id,))
        cliente = cur.fetchone()
        if not cliente:
            raise HTTPException(404, "Cliente não encontrado")

        cur.execute("""
            SELECT
                'voo'              AS tipo,
                fr.id              AS reserva_id,
                f.flight_number    AS descricao,
                f.departure_time   AS data,
                fr.status,
                p.amount,
                p.payment_method,
                fr.seat_number     AS detalhe
            FROM flight_reservations fr
            JOIN flights f ON f.id = fr.flight_id
            LEFT JOIN payments p
                ON  p.reservation_id   = fr.id
                AND p.reservation_type = 'flight'
            WHERE fr.customer_id = %s

            UNION ALL

            SELECT
                'hotel'            AS tipo,
                hr.id              AS reserva_id,
                h.name             AS descricao,
                hr.check_in        AS data,
                hr.status,
                p.amount,
                p.payment_method,
                CONCAT(hr.check_in, ' → ', hr.check_out) AS detalhe
            FROM hotel_reservations hr
            JOIN rooms r  ON r.id  = hr.room_id
            JOIN hotels h ON h.id  = r.hotel_id
            LEFT JOIN payments p
                ON  p.reservation_id   = hr.id
                AND p.reservation_type = 'hotel'
            WHERE hr.customer_id = %s

            ORDER BY data DESC
        """, (customer_id, customer_id))

        reservas = cur.fetchall()
        return {
            "cliente":  cliente,
            "reservas": reservas,
            "total":    len(reservas),
        }


# ── Relatórios ────────────────────────────────────────────────────────────
@router.get("/relatorios/ocupacao")
def relatorio_ocupacao(
    data_inicio: Optional[date] = Query(None),
    data_fim:    Optional[date] = Query(None),
    db=Depends(get_db)
):
    """
    GET /relatorios/ocupacao
    Taxa de ocupação por voo e por quarto de hotel no período.
    Consulta C2 do trabalho.
    """
    with db.cursor() as cur:
        # Ocupação por voo (C2)
        cur.execute("""
            SELECT
                f.flight_number,
                f.departure_time,
                COUNT(fr.id)                                     AS total_reservas,
                f.total_seats,
                ROUND(COUNT(fr.id)::numeric / f.total_seats * 100, 2)
                                                                 AS ocupacao_pct
            FROM flights f
            LEFT JOIN flight_reservations fr
                ON  fr.flight_id = f.id
                AND fr.status    = 'confirmed'
            WHERE f.departure_time >= NOW() - INTERVAL '30 days'
            GROUP BY f.id, f.flight_number, f.departure_time, f.total_seats
            ORDER BY ocupacao_pct DESC
            LIMIT 20
        """)
        voos = cur.fetchall()

        # Ocupação por hotel
        params  = []
        filtros = ["hr.status = 'confirmed'"]
        if data_inicio:
            filtros.append("hr.check_in >= %s")
            params.append(data_inicio)
        if data_fim:
            filtros.append("hr.check_out <= %s")
            params.append(data_fim)
        where = " AND ".join(filtros)

        cur.execute(f"""
            SELECT
                h.name          AS hotel,
                COUNT(hr.id)    AS total_reservas,
                ROUND(AVG(
                    (hr.check_out - hr.check_in)
                )::numeric, 1)  AS media_noites
            FROM hotel_reservations hr
            JOIN rooms r  ON r.id  = hr.room_id
            JOIN hotels h ON h.id  = r.hotel_id
            WHERE {where}
            GROUP BY h.id, h.name
            ORDER BY total_reservas DESC
            LIMIT 20
        """, params)
        hoteis = cur.fetchall()

    return {
        "ocupacao_voos":   voos,
        "ocupacao_hoteis": hoteis,
    }


# ── Teste de falha em transação ───────────────────────────────────────────
@router.post("/test/falha-transacao")
def testar_falha_transacao(db=Depends(get_db)):
    """
    POST /test/falha-transacao
    Demonstra que o ROLLBACK automático impede persistência de dados
    quando uma exceção ocorre antes do COMMIT.
    """
    with db.cursor() as cur:
        try:
            # Insere um registro de teste
            cur.execute("""
                INSERT INTO flight_reservations
                    (customer_id, flight_id, seat_number, status)
                VALUES (1, 1, '99Z', 'pending')
            """)
            # Força exceção ANTES do commit
            raise RuntimeError("Falha simulada antes do COMMIT")
            db.commit()   # nunca executado
        except RuntimeError as e:
            db.rollback()
            # Verifica que o registro NÃO foi persistido
            cur.execute("""
                SELECT COUNT(*) AS count
                FROM flight_reservations
                WHERE seat_number = '99Z'
            """)
            count = cur.fetchone()["count"]
            return {
                "resultado":   "ROLLBACK executado com sucesso",
                "motivo":      str(e),
                "persistido":  count > 0,   # deve ser False
                "log":         "Verifique pg_log: deve conter ROLLBACK",
            }
