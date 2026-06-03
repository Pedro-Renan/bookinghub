-- ============================================================
--  BookingHub — schema.sql
--  DDL completo: tabelas, constraints, índices
--  PostgreSQL 16
-- ============================================================

-- Extensões úteis
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- buscas por similaridade textual

-- ============================================================
--  TABELAS
-- ============================================================

-- Aeroportos
CREATE TABLE airports (
    id      SERIAL PRIMARY KEY,
    code    CHAR(3)      NOT NULL,
    name    VARCHAR(120) NOT NULL,
    city    VARCHAR(80)  NOT NULL,
    country VARCHAR(60)  NOT NULL DEFAULT 'Brasil',
    CONSTRAINT uq_airports_code UNIQUE (code),
    CONSTRAINT ck_airports_code CHECK (length(trim(code)) = 3)
);

-- Hotéis
CREATE TABLE hotels (
    id      SERIAL PRIMARY KEY,
    name    VARCHAR(120) NOT NULL,
    city    VARCHAR(80)  NOT NULL,
    country VARCHAR(60)  NOT NULL DEFAULT 'Brasil',
    stars   SMALLINT     NOT NULL,
    address VARCHAR(200),
    CONSTRAINT ck_hotels_stars CHECK (stars BETWEEN 1 AND 5)
);

-- Quartos
CREATE TABLE rooms (
    id             SERIAL PRIMARY KEY,
    hotel_id       INTEGER      NOT NULL REFERENCES hotels(id) ON DELETE CASCADE,
    room_number    VARCHAR(10)  NOT NULL,
    type           VARCHAR(10)  NOT NULL,
    capacity       SMALLINT     NOT NULL DEFAULT 2,
    price_per_night NUMERIC(10,2) NOT NULL,
    CONSTRAINT ck_rooms_type     CHECK (type IN ('single','double','suite')),
    CONSTRAINT ck_rooms_capacity CHECK (capacity > 0),
    CONSTRAINT ck_rooms_price    CHECK (price_per_night > 0),
    CONSTRAINT uq_rooms_hotel_number UNIQUE (hotel_id, room_number)
);

-- Voos
CREATE TABLE flights (
    id                    SERIAL PRIMARY KEY,
    flight_number         VARCHAR(10)  NOT NULL,
    origin_airport_id     INTEGER      NOT NULL REFERENCES airports(id),
    destination_airport_id INTEGER     NOT NULL REFERENCES airports(id),
    departure_time        TIMESTAMPTZ  NOT NULL,
    arrival_time          TIMESTAMPTZ  NOT NULL,
    total_seats           SMALLINT     NOT NULL,
    available_seats       SMALLINT     NOT NULL,
    price                 NUMERIC(10,2) NOT NULL,
    CONSTRAINT ck_flights_seats_total    CHECK (total_seats > 0),
    CONSTRAINT ck_flights_seats_avail    CHECK (available_seats >= 0),
    CONSTRAINT ck_flights_seats_max      CHECK (available_seats <= total_seats),
    CONSTRAINT ck_flights_times          CHECK (arrival_time > departure_time),
    CONSTRAINT ck_flights_price          CHECK (price > 0),
    CONSTRAINT ck_flights_diff_airports  CHECK (origin_airport_id <> destination_airport_id)
);

-- Clientes
CREATE TABLE customers (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(120) NOT NULL,
    email      VARCHAR(120) NOT NULL,
    cpf        CHAR(11)     NOT NULL,
    phone      VARCHAR(20),
    created_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_customers_email UNIQUE (email),
    CONSTRAINT uq_customers_cpf   UNIQUE (cpf),
    CONSTRAINT ck_customers_cpf   CHECK (length(trim(cpf)) = 11)
);

-- Reservas de voo
CREATE TABLE flight_reservations (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER     NOT NULL REFERENCES customers(id),
    flight_id   INTEGER     NOT NULL REFERENCES flights(id),
    seat_number VARCHAR(4)  NOT NULL,
    status      VARCHAR(12) NOT NULL DEFAULT 'pending',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_fr_status CHECK (status IN ('pending','confirmed','cancelled'))
);

-- Reservas de hotel
CREATE TABLE hotel_reservations (
    id          SERIAL PRIMARY KEY,
    customer_id INTEGER       NOT NULL REFERENCES customers(id),
    room_id     INTEGER       NOT NULL REFERENCES rooms(id),
    check_in    DATE          NOT NULL,
    check_out   DATE          NOT NULL,
    status      VARCHAR(12)   NOT NULL DEFAULT 'pending',
    total_price NUMERIC(10,2) NOT NULL,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_hr_dates  CHECK (check_out > check_in),
    CONSTRAINT ck_hr_status CHECK (status IN ('pending','confirmed','cancelled')),
    CONSTRAINT ck_hr_price  CHECK (total_price > 0)
);

-- Pagamentos
CREATE TABLE payments (
    id               SERIAL PRIMARY KEY,
    reservation_type VARCHAR(6)    NOT NULL,
    reservation_id   INTEGER       NOT NULL,
    amount           NUMERIC(10,2) NOT NULL,
    status           VARCHAR(12)   NOT NULL DEFAULT 'pending',
    payment_method   VARCHAR(20)   NOT NULL DEFAULT 'credit_card',
    created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_payments_type   CHECK (reservation_type IN ('flight','hotel')),
    CONSTRAINT ck_payments_status CHECK (status IN ('pending','confirmed','refunded')),
    CONSTRAINT ck_payments_amount CHECK (amount > 0),
    CONSTRAINT ck_payments_method CHECK (payment_method IN
        ('credit_card','debit_card','pix','bank_transfer'))
);

-- ============================================================
--  ÍNDICES
-- ============================================================

-- C1: Voos disponíveis com filtro por cidade e período
CREATE INDEX idx_airports_city
    ON airports (city);

CREATE INDEX idx_flights_departure
    ON flights (departure_time);

-- Índice parcial: exclui voos já lotados do índice (reduz tamanho ~35%)
CREATE INDEX idx_flights_available_dep
    ON flights (available_seats, departure_time)
    WHERE available_seats > 0;

-- C2: Taxa de ocupação por voo (GROUP BY + LEFT JOIN)
CREATE INDEX idx_fr_flight_status
    ON flight_reservations (flight_id, status);

-- C3: Detecção de conflito de datas em quartos
-- Índice parcial: exclui reservas canceladas
CREATE INDEX idx_hr_room_dates
    ON hotel_reservations (room_id, check_in, check_out)
    WHERE status != 'cancelled';

CREATE INDEX idx_rooms_hotel
    ON rooms (hotel_id);

-- C4: Histórico completo do cliente (UNION ALL)
CREATE INDEX idx_fr_customer
    ON flight_reservations (customer_id, created_at DESC);

CREATE INDEX idx_hr_customer
    ON hotel_reservations (customer_id, created_at DESC);

-- Pagamentos: LEFT JOIN por (reservation_type, reservation_id)
CREATE INDEX idx_pay_res
    ON payments (reservation_type, reservation_id);

-- Extra: índice de texto para busca por nome de hotel
CREATE INDEX idx_hotels_name_trgm
    ON hotels USING GIN (name gin_trgm_ops);

-- Índice para relatório de ocupação por período
CREATE INDEX idx_hr_checkin
    ON hotel_reservations (check_in, check_out)
    WHERE status != 'cancelled';

-- ============================================================
--  FUNÇÃO: atualizar updated_at automaticamente
-- ============================================================
CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_fr_updated_at
    BEFORE UPDATE ON flight_reservations
    FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
