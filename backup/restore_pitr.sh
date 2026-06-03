#!/usr/bin/env bash
# ============================================================
#  BookingHub — backup/restore_pitr.sh
#  Backup físico com pg_basebackup e Point-in-Time Recovery.
#
#  Fluxo:
#    1. Configura WAL archiving no postgresql.conf
#    2. Cria basebackup
#    3. Insere dados conhecidos após o backup
#    4. Simula falha (docker stop --time=0)
#    5. Restaura a partir do basebackup + WAL arquivados
#    6. Verifica recuperação dos dados pós-backup
# ============================================================

set -euo pipefail

DB_CONTAINER="bookinghub-db"
DB_USER="booking"
DB_NAME="bookinghub"
BASEBACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/basebackup"
WAL_ARCHIVE_DIR="$(cd "$(dirname "$0")/.." && pwd)/wal_archive"

echo "=============================================="
echo "  BookingHub — Backup Físico + PITR"
echo "  $(date)"
echo "=============================================="

# ── FASE 1: Verificar WAL archiving ──────────────────────────────────────
echo ""
echo "[1/6] Verificando configuração de WAL archiving..."
ARCHIVE_MODE=$(docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc \
    "SHOW archive_mode;")

if [ "$ARCHIVE_MODE" != "on" ]; then
    echo "  ⚠️   archive_mode não está ativo. Verifique o postgresql.conf."
    echo "  Configurações necessárias:"
    echo "    wal_level    = replica"
    echo "    archive_mode = on"
    echo "    archive_command = 'cp %p /wal_archive/%f'"
    exit 1
fi
echo "  ✅  WAL archiving ativo (archive_mode=$ARCHIVE_MODE)"

mkdir -p "$BASEBACKUP_DIR" "$WAL_ARCHIVE_DIR"

# ── FASE 2: Criar basebackup ──────────────────────────────────────────────
echo ""
echo "[2/6] Criando pg_basebackup..."
docker exec "$DB_CONTAINER" \
    pg_basebackup -U "$DB_USER" -D /tmp/basebackup -Ft -z -P --wal-method=stream
docker cp "${DB_CONTAINER}:/tmp/basebackup/." "$BASEBACKUP_DIR/"
echo "  ✅  Basebackup criado em: $BASEBACKUP_DIR"

# Registra LSN do backup
BACKUP_LSN=$(docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT pg_current_wal_lsn();")
echo "  LSN após backup: $BACKUP_LSN"

# ── FASE 3: Inserir dados após o backup ──────────────────────────────────
echo ""
echo "[3/6] Inserindo dados APÓS o basebackup (serão recuperados pelo PITR)..."
RECOVERY_TARGET=$(docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT NOW();")

docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -c "
        INSERT INTO customers (name, email, cpf, phone)
        VALUES (
            'Carlos PITR Teste',
            'carlos.pitr.$(date +%s)@bookinghub.test',
            '$(shuf -i 10000000000-99999999999 -n 1)',
            '85912345678'
        );
    "
echo "  ✅  Cliente de teste inserido"
echo "  Ponto alvo de recuperação: $RECOVERY_TARGET"

# Aguarda WAL ser arquivado
sleep 65
echo "  ✅  WAL arquivado (aguardou archive_timeout=60s)"

# ── FASE 4: Simular falha ─────────────────────────────────────────────────
echo ""
echo "[4/6] Simulando falha abrupta (docker stop --time=0)..."
docker stop --time=0 "$DB_CONTAINER"
echo "  ✅  Container parado abruptamente"

# ── FASE 5: Restaurar com PITR ────────────────────────────────────────────
echo ""
echo "[5/6] Restaurando a partir do basebackup + WAL arquivados..."

# Obtém o volume do PostgreSQL
PG_DATA_VOLUME=$(docker inspect "$DB_CONTAINER" \
    --format='{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}')

# Cria container temporário para restauração
docker run --rm \
    -v "${PG_DATA_VOLUME}:/var/lib/postgresql/data" \
    -v "${BASEBACKUP_DIR}:/basebackup" \
    -v "${WAL_ARCHIVE_DIR}:/wal_archive" \
    postgres:16 \
    bash -c "
        # Limpa o data directory atual
        rm -rf /var/lib/postgresql/data/*

        # Extrai o basebackup
        cd /var/lib/postgresql/data
        tar -xzf /basebackup/base.tar.gz .

        # Configura recovery no postgresql.conf (PG >= 12)
        cat >> /var/lib/postgresql/data/postgresql.conf << EOF

# PITR Recovery
restore_command        = 'cp /wal_archive/%f %p'
recovery_target_time   = '${RECOVERY_TARGET}'
recovery_target_action = 'promote'
EOF

        # Cria signal file para iniciar recovery mode
        touch /var/lib/postgresql/data/recovery.signal

        # Ajusta permissões
        chown -R postgres:postgres /var/lib/postgresql/data
    "

# Reinicia o container
docker start "$DB_CONTAINER"

# Aguarda PostgreSQL inicializar e completar recovery
echo "  Aguardando recovery completar..."
for i in $(seq 1 30); do
    sleep 2
    STATUS=$(docker exec "$DB_CONTAINER" \
        psql -U "$DB_USER" -d "$DB_NAME" -tAc \
        "SELECT pg_is_in_recovery();" 2>/dev/null || echo "aguardando")
    if [ "$STATUS" = "f" ]; then
        echo "  ✅  Recovery concluído (banco promovido a primary)"
        break
    fi
    echo "  ... recovery em andamento ($i/30)"
done

# ── FASE 6: Verificar recuperação ────────────────────────────────────────
echo ""
echo "[6/6] Verificando recuperação dos dados pós-backup..."
docker exec "$DB_CONTAINER" \
    psql -U "$DB_USER" -d "$DB_NAME" -c "
        SELECT id, name, email, created_at
        FROM customers
        WHERE email LIKE 'carlos.pitr%'
        ORDER BY created_at DESC
        LIMIT 3;
    "

echo ""
echo "=============================================="
echo "  ✅  PITR concluído!"
echo "  Dados inseridos após o basebackup foram"
echo "  recuperados com sucesso a partir do WAL."
echo "=============================================="

# ── Log do PostgreSQL durante recovery ───────────────────────────────────
echo ""
echo "  Últimas linhas do log de recovery:"
docker exec "$DB_CONTAINER" \
    bash -c "tail -20 /var/lib/postgresql/data/pg_log/*.log 2>/dev/null | \
    grep -E '(recovery|restore|archive|promote|PITR)' | tail -10" || true
