"""
BookingHub — api/routers/reservas.py
Endpoints de escrita: criação e cancelamento de reservas.
Implementa controle de concorrência com SELECT FOR UPDATE.
"""

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import date
from api.utils.db import get_db
from api.utils.retry import executar_com_retry

router = APIRouter(prefix="/reservas", tags=["Reservas"])


# ── Schemas ───────────────────────────────────────────────────────────────
class ReservaVooPayload(BaseModel):
    customer_id: int
    flight_id:   int


class ReservaHotelPayload(BaseModel):
    customer_id: int
    room_id:     int
    check_in:    date
    check_out:   date


class PacotePayload(BaseModel):
    customer_id: int
    flight_id:   int
    room_id:     int
    check_in:    date
    check_out:   date


# ── Funções auxiliares ────────────────────────────────────────────────────
def _proximo_assento(cur, flight_id: int) -> str:
    """Gera o próximo número de assento disponível para o voo."""
    cur.execute("""
        SELECT seat_number FROM flight_reservations
        WHERE flight_id = %s AND status != 'cancelled'
    """, (flight_id,))
    ocupados = {r["seat_number"] for r in cur.fetchall()}
    fileiras = "ABCDEF"
    for num in range(1, 60):
        for letra in fileiras:
            seat = f"{letra}{num}"
            if seat not in ocupados:
                return seat
    return f"X{len(ocupados)+1}"


def _criar_reserva_voo_tx(cur, customer_id: int, flight_id: int) -> dict:
    """
    Cria reserva de voo dentro de uma transação com SELECT FOR UPDATE.
    Garante atomicidade da verificação + decremento de vagas.
    """
    # 1. Verifica se cliente existe
    cur.execute("SELECT id FROM customers WHERE id = %s", (customer_id,))
    if not cur.fetchone():
        raise HTTPException(404, f"Cliente {customer_id} não encontrado")

    # 2. Bloqueia a linha do voo para evitar leitura fantasma / overbooking
    cur.execute("""
        SELECT id, flight_number, available_seats, price
        FROM flights
        WHERE id = %s
        FOR UPDATE
    """, (flight_id,))
    voo = cur.fetchone()
    if not voo:
        raise HTTPException(404, f"Voo {flight_id} não encontrado")

    if voo["available_seats"] <= 0:
        raise HTTPException(409, "Sem assentos disponíveis para este voo")

    # 3. Decrementa vagas atomicamente
    cur.execute("""
        UPDATE flights
        SET available_seats = available_seats - 1
        WHERE id = %s
    """, (flight_id,))

    # 4. Cria a reserva
    seat = _proximo_assento(cur, flight_id)
    cur.execute("""
        INSERT INTO flight_reservations
            (customer_id, flight_id, seat_number, status)
        VALUES (%s, %s, %s, 'pending')
        RETURNING id
    """, (customer_id, flight_id, seat))
    reserva_id = cur.fetchone()["id"]

    return {
        "reserva_id":    reserva_id,
        "tipo":          "voo",
        "flight_number": voo["flight_number"],
        "seat_number":   seat,
        "status":        "pending",
        "preco":         float(voo["price"]),
    }


def _criar_reserva_hotel_tx(cur, customer_id: int, room_id: int,
                             check_in: date, check_out: date) -> dict:
    """
    Cria reserva de hotel com verificação de conflito de datas.
    Usa SELECT FOR UPDATE para bloquear reservas conflitantes.
    """
    if check_out <= check_in:
        raise HTTPException(400, "check_out deve ser posterior a check_in")

    # 1. Verifica quarto e bloqueia conflitos
    cur.execute("""
        SELECT id FROM hotel_reservations
        WHERE room_id    = %s
          AND status    != 'cancelled'
          AND check_in   < %s
          AND check_out  > %s
        FOR UPDATE
    """, (room_id, check_out, check_in))
    conflito = cur.fetchone()
    if conflito:
        raise HTTPException(
            409,
            f"Quarto {room_id} já reservado para o período {check_in} — {check_out}"
        )

    # 2. Busca preço do quarto
    cur.execute("""
        SELECT r.id, r.room_number, r.price_per_night,
               h.name AS hotel_nome
        FROM rooms r
        JOIN hotels h ON h.id = r.hotel_id
        WHERE r.id = %s
        FOR UPDATE
    """, (room_id,))
    quarto = cur.fetchone()
    if not quarto:
        raise HTTPException(404, f"Quarto {room_id} não encontrado")

    nights      = (check_out - check_in).days
    total_price = float(quarto["price_per_night"]) * nights

    # 3. Insere reserva
    cur.execute("""
        INSERT INTO hotel_reservations
            (customer_id, room_id, check_in, check_out, status, total_price)
        VALUES (%s, %s, %s, %s, 'pending', %s)
        RETURNING id
    """, (customer_id, room_id, check_in, check_out, total_price))
    reserva_id = cur.fetchone()["id"]

    return {
        "reserva_id":  reserva_id,
        "tipo":        "hotel",
        "hotel":       quarto["hotel_nome"],
        "quarto":      quarto["room_number"],
        "check_in":    str(check_in),
        "check_out":   str(check_out),
        "noites":      nights,
        "total_price": total_price,
        "status":      "pending",
    }


# ── Endpoints ─────────────────────────────────────────────────────────────
@router.post("/voo", status_code=201)
def criar_reserva_voo(payload: ReservaVooPayload, db=Depends(get_db)):
    """
    POST /reservas/voo
    Cria reserva de voo com controle de overbooking via SELECT FOR UPDATE.
    Retorna HTTP 409 se não houver assentos disponíveis.
    """
    def _executar():
        with db:
            with db.cursor() as cur:
                return _criar_reserva_voo_tx(
                    cur, payload.customer_id, payload.flight_id
                )
    try:
        return executar_com_retry(_executar)
    except psycopg2.errors.SerializationFailure:
        raise HTTPException(409, "Conflito de concorrência. Tente novamente.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro interno: {str(e)}")


@router.post("/hotel", status_code=201)
def criar_reserva_hotel(payload: ReservaHotelPayload, db=Depends(get_db)):
    """
    POST /reservas/hotel
    Cria reserva de hotel com verificação de conflito de datas.
    Usa isolamento SERIALIZABLE + SELECT FOR UPDATE.
    Retorna HTTP 409 em caso de conflito de datas.
    """
    def _executar():
        with db:
            with db.cursor() as cur:
                # Nível de isolamento SERIALIZABLE para detecção de conflitos
                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                return _criar_reserva_hotel_tx(
                    cur,
                    payload.customer_id,
                    payload.room_id,
                    payload.check_in,
                    payload.check_out,
                )
    try:
        return executar_com_retry(_executar)
    except psycopg2.errors.SerializationFailure:
        raise HTTPException(409, "Conflito de concorrência. Tente novamente.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro interno: {str(e)}")


@router.post("/pacote", status_code=201)
def criar_reserva_pacote(payload: PacotePayload, db=Depends(get_db)):
    """
    POST /reservas/pacote
    Reserva voo + hotel em uma única transação.
    Usa SAVEPOINT para desfazer apenas a reserva de hotel em caso de falha,
    mantendo a reserva de voo confirmada.
    """
    def _executar():
        with db:
            with db.cursor() as cur:
                # Reserva o voo primeiro
                res_voo = _criar_reserva_voo_tx(
                    cur, payload.customer_id, payload.flight_id
                )

                # SAVEPOINT antes da reserva de hotel
                cur.execute("SAVEPOINT sp_hotel")
                try:
                    res_hotel = _criar_reserva_hotel_tx(
                        cur,
                        payload.customer_id,
                        payload.room_id,
                        payload.check_in,
                        payload.check_out,
                    )
                except HTTPException as e:
                    # Desfaz apenas o hotel; voo permanece
                    cur.execute("ROLLBACK TO SAVEPOINT sp_hotel")
                    raise HTTPException(
                        422,
                        f"Hotel indisponível (voo reservado com sucesso): {e.detail}"
                    )

                return {
                    "voo":   res_voo,
                    "hotel": res_hotel,
                }

    try:
        return executar_com_retry(_executar)
    except psycopg2.errors.SerializationFailure:
        raise HTTPException(409, "Conflito de concorrência. Tente novamente.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erro interno: {str(e)}")


@router.delete("/{tipo}/{reserva_id}", status_code=200)
def cancelar_reserva(tipo: str, reserva_id: int, db=Depends(get_db)):
    """
    DELETE /reservas/{tipo}/{id}
    Cancela reserva (voo ou hotel) e restaura disponibilidade.
    tipo: 'voo' | 'hotel'
    """
    if tipo not in ("voo", "hotel"):
        raise HTTPException(400, "tipo deve ser 'voo' ou 'hotel'")

    with db:
        with db.cursor() as cur:
            if tipo == "voo":
                cur.execute("""
                    SELECT id, flight_id, status
                    FROM flight_reservations
                    WHERE id = %s
                    FOR UPDATE
                """, (reserva_id,))
                res = cur.fetchone()
                if not res:
                    raise HTTPException(404, "Reserva não encontrada")
                if res["status"] == "cancelled":
                    raise HTTPException(409, "Reserva já cancelada")

                # Cancela reserva
                cur.execute("""
                    UPDATE flight_reservations
                    SET status = 'cancelled', updated_at = NOW()
                    WHERE id = %s
                """, (reserva_id,))

                # Restaura assento
                cur.execute("""
                    UPDATE flights
                    SET available_seats = available_seats + 1
                    WHERE id = %s
                """, (res["flight_id"],))

            else:  # hotel
                cur.execute("""
                    SELECT id, status
                    FROM hotel_reservations
                    WHERE id = %s
                    FOR UPDATE
                """, (reserva_id,))
                res = cur.fetchone()
                if not res:
                    raise HTTPException(404, "Reserva não encontrada")
                if res["status"] == "cancelled":
                    raise HTTPException(409, "Reserva já cancelada")

                cur.execute("""
                    UPDATE hotel_reservations
                    SET status = 'cancelled'
                    WHERE id = %s
                """, (reserva_id,))

    return {"mensagem": f"Reserva {reserva_id} cancelada com sucesso"}
