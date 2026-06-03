#!/usr/bin/env bash
# ============================================================
#  BookingHub — backup/backup_logico.sh
#  Backup lógico com pg_dump (formato custom) e verificação
#  de integridade na restauração.
# ============================================================

set -euo pipefail

# ── Configurações ─────────────────────────────────────────────────────────
DB_CONTAINER="bookinghub-db"
DB_USER="booking"
DB_NAME="bookinghub"
DB_RESTORED="${DB_NAME}_restored"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/dumps"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
DUMP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.dump"

mkdir -p "$BACKUP_DIR"

echo "=============================================="
echo "  BookingHub — Backup Lógico com pg_dump"
echo "  $(date)"
echo "=============================================="

# ── 1. Dump completo em formato custom ───────────────────────────────────
echo ""
echo "[1/4] Gerando dump: $DUMP_FILE"
docker exec "$DB_CONTAINER" \
    pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$DUMP_FILE"

TAMANHO=$(du -sh "$DUMP_FILE" | cut -f1)
echo "  ✅  Dump gerado com sucesso — tamanho: $TAMANHO"

# ── 2. Criar banco de destino para verificação ───────────────────────────
echo ""
echo "[2/4] Criando banco de destino: $DB_RESTORED"
docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d postgres -c \
    "DROP DATABASE IF EXISTS ${DB_RESTORED};" > /dev/null
docker exec "$DB_CONTAINER" \
    createdb -U "$DB_USER" "$DB_RESTORED"
echo "  ✅  Banco $DB_RESTORED criado"

# ── 3. Restaurar ─────────────────────────────────────────────────────────
echo ""
echo "[3/4] Restaurando backup..."
# Copia o dump para dentro do container
docker cp "$DUMP_FILE" "${DB_CONTAINER}:/tmp/restore.dump"
docker exec "$DB_CONTAINER" \
    pg_restore -U "$DB_USER" -d "$DB_RESTORED" /tmp/restore.dump
echo "  ✅  Restauração concluída"

# ── 4. Verificar integridade ──────────────────────────────────────────────
echo ""
echo "[4/4] Verificando integridade (contagem de registros):"
echo ""
docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_RESTORED" -c \
    "SELECT tablename AS tabela,
            n_live_tup AS registros
     FROM pg_stat_user_tables
     WHERE schemaname = 'public'
     ORDER BY tablename;" 2>/dev/null || \
docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_RESTORED" -c "
        SELECT 'airports'            AS tabela, COUNT(*) FROM airports
        UNION ALL
        SELECT 'customers',                     COUNT(*) FROM customers
        UNION ALL
        SELECT 'flight_reservations',           COUNT(*) FROM flight_reservations
        UNION ALL
        SELECT 'flights',                       COUNT(*) FROM flights
        UNION ALL
        SELECT 'hotel_reservations',            COUNT(*) FROM hotel_reservations
        UNION ALL
        SELECT 'hotels',                        COUNT(*) FROM hotels
        UNION ALL
        SELECT 'payments',                      COUNT(*) FROM payments
        UNION ALL
        SELECT 'rooms',                         COUNT(*) FROM rooms
        ORDER BY tabela;
    "

echo ""
echo "=============================================="
echo "  ✅  Backup lógico concluído com sucesso!"
echo "  Arquivo: $DUMP_FILE"
echo "=============================================="
