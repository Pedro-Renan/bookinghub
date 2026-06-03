"""
BookingHub — api/main.py
Ponto de entrada da API FastAPI.
"""

import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from api.routers import voos, hoteis, reservas, pagamentos

app = FastAPI(
    title="BookingHub API",
    description=(
        "Plataforma de reservas de hotéis e passagens aéreas. "
        "Trabalho Final — Banco de Dados — UniCatólica Quixadá."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Registra os roteadores
app.include_router(voos.router)
app.include_router(hoteis.router)
app.include_router(reservas.router)
app.include_router(pagamentos.router)


@app.get("/health", tags=["Sistema"])
def health_check():
    """Verifica se a API está no ar."""
    return {"status": "ok", "versao": "1.0.0"}


@app.get("/", tags=["Sistema"])
def root():
    return {
        "projeto": "BookingHub",
        "docs":    "/docs",
        "health":  "/health",
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
