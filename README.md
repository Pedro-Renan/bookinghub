# BookingHub 🛫🏨

Plataforma de reservas de hotéis e passagens aéreas com foco em **alta concorrência**, desenvolvida como trabalho final da disciplina de Banco de Dados — UniCatólica Quixadá.

## Equipe

| Nome | Responsabilidade |
|------|-----------------|
| Pedro Henrique Melo Costa | Arquitetura geral e API |
| Ana Carolina Ferreira Lima | Modelo de dados e seed |
| João Victor Andrade Souza | Índices e otimização |
| Mariana Pinto Rodrigues | Transações e concorrência |
| Lucas Bezerra de Oliveira | Recuperação de falhas |

## Stack

- **SGBD:** PostgreSQL 16
- **API:** Python 3.11 + FastAPI + psycopg2
- **Infra:** Docker Compose

---

## Como executar localmente

### Pré-requisitos

- Docker e Docker Compose instalados
- Python 3.11+ (para rodar os scripts de teste fora do container)

### 1. Clonar o repositório

```bash
git clone https://github.com/seu-usuario/bookinghub.git
cd bookinghub
```

### 2. Subir os containers

```bash
docker-compose up -d
```

Aguarde o PostgreSQL inicializar (~10 segundos).

### 3. Criar o schema

```bash
docker exec -i bookinghub-db psql -U booking -d bookinghub < schema.sql
```

### 4. Popular o banco (seed)

```bash
# Instalar dependências
pip install psycopg2-binary faker

# Rodar o seed (~16.000 registros)
python seed.py
```

### 5. Verificar a API

```bash
# Health check
curl http://localhost:8000/health

# Documentação interativa
open http://localhost:8000/docs
```

---

## Endpoints disponíveis

### Consulta
| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/voos/disponiveis` | Lista voos com filtro de origem, destino e data |
| GET | `/hoteis/disponiveis` | Lista hotéis com quartos livres no período |
| GET | `/clientes/{id}/reservas` | Histórico completo de reservas do cliente |
| GET | `/relatorios/ocupacao` | Taxa de ocupação por voo e por quarto |

### Escrita
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/reservas/voo` | Cria reserva de voo (com controle de overbooking) |
| POST | `/reservas/hotel` | Cria reserva de hotel (com verificação de conflito de datas) |
| POST | `/pagamentos` | Registra pagamento e confirma reserva |
| DELETE | `/reservas/{tipo}/{id}` | Cancela reserva e restaura disponibilidade |

### Testes
| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/test/falha-transacao` | Demonstra rollback automático |

---

## Rodando os testes de concorrência

```bash
# Instalar dependências de teste
pip install requests

# Teste de overbooking (50 threads simultâneas)
python testes/test_overbooking.py

# Teste de conflito de datas em hotel (30 threads)
python testes/test_conflito_datas.py

# Suite de níveis de isolamento
python testes/test_isolamento.py
```

---

## Backup e recuperação

```bash
# Backup lógico
bash backup/backup_logico.sh

# Restauração PITR
bash backup/restore_pitr.sh
```

---

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `DATABASE_URL` | `postgresql://booking:secret@localhost:5432/bookinghub` | URL de conexão |
| `API_PORT` | `8000` | Porta da API |

---

## Estrutura do repositório

```
bookinghub/
├── README.md
├── schema.sql
├── seed.py
├── docker-compose.yml
├── postgresql.conf
├── api/
│   ├── main.py
│   ├── routers/
│   │   ├── voos.py
│   │   ├── hoteis.py
│   │   ├── reservas.py
│   │   └── pagamentos.py
│   └── utils/
│       ├── db.py
│       └── retry.py
├── testes/
│   ├── test_overbooking.py
│   ├── test_conflito_datas.py
│   └── test_isolamento.py
├── backup/
│   ├── backup_logico.sh
│   └── restore_pitr.sh
└── relatorio.pdf
```
