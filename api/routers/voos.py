"""
BookingHub — api/routers/voos.py
Endpoints de consulta relacionados a voos.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from datetime import date
from api.utils.db import get_db

router = APIRouter(prefix="/voos", tags=["Voos"])


@router.get("/disponiveis")
def listar_voos_disponiveis(
    origem:  Optional[str]  = Query(None, description="Cidade de origem"),
    destino: Optional[str]  = Query(None, description="Cidade de destino"),
    data_ida: Optional[date] = Query(None, description="Data de partida (YYYY-MM-DD)"),
    data_fim: Optional[date] = Query(None, description="Data final do intervalo"),
    db=Depends(get_db)
):
    """
    GET /voos/disponiveis
    Lista voos disponíveis com filtro por origem, destino e data.
    Usa índices: idx_airports_city, idx_flights_available_dep.

    Consulta C1 do trabalho.
    """
    filtros = ["f.available_seats > 0"]
    params  = []

    if origem:
        filtros.append("a1.city ILIKE %s")
        params.append(f"%{origem}%")
    if destino:
        filtros.append("a2.city ILIKE %s")
        params.append(f"%{destino}%")
    if data_ida:
        filtros.append("f.departure_time::date >= %s")
        params.append(data_ida)
    if data_fim:
        filtros.append("f.departure_time::date <= %s")
        params.append(data_fim)
    elif data_ida:
        # Se só data_ida, busca no mesmo dia
        from datetime import timedelta
        params.append(data_ida + timedelta(days=1))
        filtros.append("f.departure_time::date < %s")

    where = " AND ".join(filtros)

    sql = f"""
        SELECT
            f.id,
            f.flight_number,
            f.departure_time,
            f.arrival_time,
            f.available_seats,
            f.price,
            a1.code AS origem_code,
            a1.city AS origem_cidade,
            a2.code AS destino_code,
            a2.city AS destino_cidade
        FROM flights f
        JOIN airports a1 ON a1.id = f.origin_airport_id
        JOIN airports a2 ON a2.id = f.destination_airport_id
        WHERE {where}
        ORDER BY f.departure_time
        LIMIT 100
    """

    with db.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


@router.get("/{voo_id}")
def detalhe_voo(voo_id: int, db=Depends(get_db)):
    """Retorna detalhes de um voo específico."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT
                f.*,
                a1.code AS origem_code, a1.city AS origem_cidade,
                a2.code AS destino_code, a2.city AS destino_cidade
            FROM flights f
            JOIN airports a1 ON a1.id = f.origin_airport_id
            JOIN airports a2 ON a2.id = f.destination_airport_id
            WHERE f.id = %s
        """, (voo_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Voo não encontrado")
        return row
