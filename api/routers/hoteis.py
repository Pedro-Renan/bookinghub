"""
BookingHub — api/routers/hoteis.py
Endpoints de consulta relacionados a hotéis e quartos.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import date
from api.utils.db import get_db

router = APIRouter(prefix="/hoteis", tags=["Hotéis"])


@router.get("/disponiveis")
def listar_hoteis_disponiveis(
    cidade:     Optional[str]  = Query(None),
    check_in:   Optional[date] = Query(None),
    check_out:  Optional[date] = Query(None),
    estrelas:   Optional[int]  = Query(None, ge=1, le=5),
    db=Depends(get_db)
):
    """
    GET /hoteis/disponiveis
    Lista hotéis com quartos livres para o período informado.
    Usa índice: idx_hr_room_dates (parcial).

    Consulta C3 do trabalho (adaptada para endpoint).
    """
    if check_in and check_out and check_out <= check_in:
        raise HTTPException(400, "check_out deve ser posterior a check_in")

    filtros = ["1=1"]
    params  = []

    if cidade:
        filtros.append("h.city ILIKE %s")
        params.append(f"%{cidade}%")
    if estrelas:
        filtros.append("h.stars = %s")
        params.append(estrelas)

    # Subquery de quartos disponíveis no período
    disponivel_sql = ""
    if check_in and check_out:
        disponivel_sql = """
            AND r.id NOT IN (
                SELECT hr.room_id
                FROM hotel_reservations hr
                WHERE hr.status != 'cancelled'
                  AND hr.check_in  < %(check_out)s
                  AND hr.check_out > %(check_in)s
            )
        """
        params_dict = {"check_in": check_in, "check_out": check_out}
    else:
        params_dict = {}

    where = " AND ".join(filtros)

    # Monta query dinamicamente (psycopg2 aceita mistura de %s e %(nome)s
    # se usarmos apenas um formato — aqui usamos lista para os filtros
    # e depois substituímos o dict de datas)
    sql = f"""
        SELECT
            h.id           AS hotel_id,
            h.name         AS hotel_nome,
            h.city         AS cidade,
            h.stars        AS estrelas,
            COUNT(r.id)    AS quartos_disponiveis,
            MIN(r.price_per_night) AS preco_minimo
        FROM hotels h
        JOIN rooms r ON r.hotel_id = h.id
        WHERE {where}
        {disponivel_sql}
        GROUP BY h.id, h.name, h.city, h.stars
        HAVING COUNT(r.id) > 0
        ORDER BY h.stars DESC, preco_minimo
        LIMIT 50
    """

    with db.cursor() as cur:
        if params_dict:
            # executa com dict para as datas
            cur.execute(sql, {**{str(i): v for i, v in enumerate(params)},
                               **params_dict})
        else:
            # sem filtro de datas — usa lista simples
            sql_simple = f"""
                SELECT
                    h.id, h.name AS hotel_nome, h.city AS cidade,
                    h.stars AS estrelas,
                    COUNT(r.id) AS quartos_disponiveis,
                    MIN(r.price_per_night) AS preco_minimo
                FROM hotels h
                JOIN rooms r ON r.hotel_id = h.id
                WHERE {where}
                GROUP BY h.id, h.name, h.city, h.stars
                HAVING COUNT(r.id) > 0
                ORDER BY h.stars DESC, preco_minimo
                LIMIT 50
            """
            cur.execute(sql_simple, params)
        return cur.fetchall()


@router.get("/{hotel_id}/quartos")
def quartos_hotel(
    hotel_id:  int,
    check_in:  Optional[date] = Query(None),
    check_out: Optional[date] = Query(None),
    db=Depends(get_db)
):
    """
    Lista quartos de um hotel com verificação de conflito de datas.
    Consulta C3 exata do trabalho.
    """
    with db.cursor() as cur:
        cur.execute("SELECT id FROM hotels WHERE id = %s", (hotel_id,))
        if not cur.fetchone():
            raise HTTPException(404, "Hotel não encontrado")

        if check_in and check_out:
            cur.execute("""
                SELECT r.id, r.room_number, r.type, r.capacity, r.price_per_night
                FROM rooms r
                WHERE r.hotel_id = %s
                  AND r.id NOT IN (
                      SELECT hr.room_id
                      FROM hotel_reservations hr
                      WHERE hr.status != 'cancelled'
                        AND hr.check_in  < %s
                        AND hr.check_out > %s
                  )
                ORDER BY r.type, r.price_per_night
            """, (hotel_id, check_out, check_in))
        else:
            cur.execute("""
                SELECT id, room_number, type, capacity, price_per_night
                FROM rooms WHERE hotel_id = %s
                ORDER BY type, price_per_night
            """, (hotel_id,))
        return cur.fetchall()


@router.get("/relatorio/ocupacao")
def relatorio_ocupacao(
    data_inicio: Optional[date] = Query(None),
    data_fim:    Optional[date] = Query(None),
    db=Depends(get_db)
):
    """
    GET /relatorios/ocupacao
    Taxa de ocupação por quarto de hotel no período.
    """
    filtros = ["hr.status = 'confirmed'"]
    params  = []
    if data_inicio:
        filtros.append("hr.check_in >= %s")
        params.append(data_inicio)
    if data_fim:
        filtros.append("hr.check_out <= %s")
        params.append(data_fim)
    where = " AND ".join(filtros)

    with db.cursor() as cur:
        cur.execute(f"""
            SELECT
                h.name      AS hotel,
                r.room_number,
                r.type,
                COUNT(hr.id) AS total_reservas,
                ROUND(
                    COUNT(hr.id)::numeric /
                    NULLIF(
                        (SELECT COUNT(*) FROM hotel_reservations hr2
                         WHERE hr2.room_id = r.id
                           AND hr2.status != 'cancelled'), 0
                    ) * 100, 2
                ) AS ocupacao_pct
            FROM rooms r
            JOIN hotels h         ON h.id = r.hotel_id
            LEFT JOIN hotel_reservations hr ON hr.room_id = r.id
                AND {where}
            GROUP BY h.name, r.id, r.room_number, r.type
            ORDER BY ocupacao_pct DESC NULLS LAST
            LIMIT 50
        """, params)
        return cur.fetchall()
