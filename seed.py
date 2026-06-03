"""
BookingHub — seed.py
Popula o banco com dados realistas usando a biblioteca Faker.
Total estimado: ~16.600 registros distribuídos entre as 8 tabelas.

Uso:
    python seed.py
    DATABASE_URL=postgresql://booking:secret@localhost:5432/bookinghub python seed.py
"""

import os
import random
import psycopg2
from datetime import date, timedelta
from faker import Faker

# ── Configuração ──────────────────────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://booking:secret@localhost:5432/bookinghub"
)

fake = Faker("pt_BR")
Faker.seed(42)
random.seed(42)

# ── Dados fixos — aeroportos brasileiros reais ────────────────────────────
AIRPORTS = [
    ("GRU", "Aeroporto Internacional de Guarulhos",      "São Paulo",       "Brasil"),
    ("CGH", "Aeroporto de Congonhas",                    "São Paulo",       "Brasil"),
    ("SDU", "Aeroporto Santos Dumont",                   "Rio de Janeiro",  "Brasil"),
    ("GIG", "Aeroporto Internacional Tom Jobim",         "Rio de Janeiro",  "Brasil"),
    ("BSB", "Aeroporto Internacional de Brasília",       "Brasília",        "Brasil"),
    ("SSA", "Aeroporto Internacional de Salvador",       "Salvador",        "Brasil"),
    ("REC", "Aeroporto Internacional do Recife",         "Recife",          "Brasil"),
    ("FOR", "Aeroporto Internacional Pinto Martins",     "Fortaleza",       "Brasil"),
    ("POA", "Aeroporto Internacional Salgado Filho",     "Porto Alegre",    "Brasil"),
    ("BEL", "Aeroporto Internacional Val-de-Cans",       "Belém",           "Brasil"),
    ("MAO", "Aeroporto Internacional Eduardo Gomes",     "Manaus",          "Brasil"),
    ("CWB", "Aeroporto Internacional Afonso Pena",       "Curitiba",        "Brasil"),
    ("VCP", "Aeroporto Internacional de Viracopos",      "Campinas",        "Brasil"),
    ("MCZ", "Aeroporto Internacional Zumbi dos Palmares","Maceió",          "Brasil"),
    ("NAT", "Aeroporto Internacional Aluísio Alves",     "Natal",           "Brasil"),
    ("THE", "Aeroporto Internacional de Teresina",       "Teresina",        "Brasil"),
    ("SLZ", "Aeroporto Internacional Marechal Cunha",    "São Luís",        "Brasil"),
    ("CGR", "Aeroporto Internacional de Campo Grande",   "Campo Grande",    "Brasil"),
    ("CGB", "Aeroporto Internacional Marechal Rondon",   "Cuiabá",          "Brasil"),
    ("GYN", "Aeroporto Santa Genoveva",                  "Goiânia",         "Brasil"),
]

SEAT_CONFIGS = [100, 138, 150, 180, 220, 280]
HOTEL_STARS  = [1, 2, 3, 3, 4, 4, 4, 5, 5]
ROOM_TYPES   = ["single", "double", "suite"]
ROOM_PRICES  = {"single": (89, 280), "double": (149, 450), "suite": (350, 1200)}
FLIGHT_PRICES= (199.90, 2499.90)
PAY_METHODS  = ["credit_card", "debit_card", "pix", "bank_transfer"]
STATUSES_RES = ["pending", "confirmed", "confirmed", "confirmed", "cancelled"]


def random_date_range(start_offset_days=-365, end_offset_days=180):
    """Retorna (check_in, check_out) aleatório."""
    today    = date.today()
    check_in = today + timedelta(days=random.randint(start_offset_days, end_offset_days))
    nights   = random.randint(1, 14)
    return check_in, check_in + timedelta(days=nights)


def seed_airports(cur):
    print("  → Inserindo aeroportos...")
    airport_ids = []
    for code, name, city, country in AIRPORTS:
        cur.execute(
            "INSERT INTO airports (code, name, city, country) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT (code) DO NOTHING RETURNING id",
            (code, name, city, country)
        )
        row = cur.fetchone()
        if row:
            airport_ids.append(row[0])
    # Aeroportos extras para atingir volume
    extra_cities = [
        ("João Pessoa","Brasil"), ("Aracaju","Brasil"), ("Macapá","Brasil"),
        ("Porto Velho","Brasil"), ("Rio Branco","Brasil"), ("Palmas","Brasil"),
        ("Vitória","Brasil"), ("Florianópolis","Brasil"), ("Londrina","Brasil"),
        ("Uberlândia","Brasil"),
    ]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    used_codes = {a[0] for a in AIRPORTS}
    for city, country in extra_cities:
        while True:
            code = "".join(random.choices(letters, k=3))
            if code not in used_codes:
                used_codes.add(code)
                break
        cur.execute(
            "INSERT INTO airports (code, name, city, country) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (code, f"Aeroporto de {city}", city, country)
        )
        row = cur.fetchone()
        if row:
            airport_ids.append(row[0])
    # Busca todos os ids
    cur.execute("SELECT id FROM airports")
    return [r[0] for r in cur.fetchall()]


def seed_hotels(cur, n=320):
    print(f"  → Inserindo {n} hotéis...")
    cur.execute("SELECT id FROM airports")
    airports = cur.fetchall()
    cur.execute("SELECT DISTINCT city FROM airports")
    cities = [r[0] for r in cur.fetchall()]

    hotel_ids = []
    brands = ["Grand", "Plaza", "Palace", "Inn", "Suites", "Express",
              "Premium", "Comfort", "Select", "Boutique"]
    for _ in range(n):
        city = random.choice(cities)
        brand = random.choice(brands)
        name  = f"Hotel {fake.last_name()} {brand}"
        stars = random.choice(HOTEL_STARS)
        cur.execute(
            "INSERT INTO hotels (name, city, country, stars, address) "
            "VALUES (%s,%s,'Brasil',%s,%s) RETURNING id",
            (name, city, stars, fake.address().replace("\n", ", ")[:200])
        )
        hotel_ids.append(cur.fetchone()[0])
    return hotel_ids


def seed_rooms(cur, hotel_ids):
    print(f"  → Inserindo quartos para {len(hotel_ids)} hotéis...")
    room_ids = []
    for hotel_id in hotel_ids:
        n_rooms = random.randint(4, 12)
        used_numbers = set()
        for _ in range(n_rooms):
            while True:
                num = f"{random.randint(1,5)}{random.randint(1,20):02d}"
                if num not in used_numbers:
                    used_numbers.add(num)
                    break
            rtype   = random.choice(ROOM_TYPES)
            lo, hi  = ROOM_PRICES[rtype]
            price   = round(random.uniform(lo, hi), 2)
            cap     = 1 if rtype == "single" else (2 if rtype == "double" else 4)
            cur.execute(
                "INSERT INTO rooms (hotel_id, room_number, type, capacity, price_per_night) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (hotel_id, num, rtype, cap, price)
            )
            room_ids.append(cur.fetchone()[0])
    return room_ids


def seed_flights(cur, airport_ids, n=2400):
    print(f"  → Inserindo {n} voos...")
    flight_ids = []
    used_numbers = set()
    for _ in range(n):
        while True:
            fn = fake.bothify("??####").upper()
            if fn not in used_numbers:
                used_numbers.add(fn)
                break
        orig, dest = random.sample(airport_ids, 2)
        dep_delta  = random.randint(-365, 180)
        dep        = fake.date_time_between(
            start_date=f"{dep_delta}d", end_date=f"{dep_delta+1}d"
        )
        duration_h = random.uniform(1.0, 8.0)
        from datetime import timedelta as td
        arr        = dep + td(hours=duration_h)
        total      = random.choice(SEAT_CONFIGS)
        avail      = random.randint(0, total)
        price      = round(random.uniform(*FLIGHT_PRICES), 2)
        cur.execute(
            "INSERT INTO flights "
            "(flight_number, origin_airport_id, destination_airport_id, "
            " departure_time, arrival_time, total_seats, available_seats, price) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (fn, orig, dest, dep, arr, total, avail, price)
        )
        flight_ids.append(cur.fetchone()[0])
    return flight_ids


def seed_customers(cur, n=3000):
    print(f"  → Inserindo {n} clientes...")
    customer_ids = []
    used_emails = set()
    used_cpfs   = set()
    for _ in range(n):
        while True:
            email = fake.email()
            if email not in used_emails:
                used_emails.add(email)
                break
        while True:
            cpf = fake.cpf().replace(".", "").replace("-", "")
            if cpf not in used_cpfs:
                used_cpfs.add(cpf)
                break
        cur.execute(
            "INSERT INTO customers (name, email, cpf, phone) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (fake.name(), email, cpf, fake.phone_number()[:20])
        )
        customer_ids.append(cur.fetchone()[0])
    return customer_ids


def seed_flight_reservations(cur, customer_ids, flight_ids, n=2900):
    print(f"  → Inserindo {n} reservas de voo...")
    fr_ids = []
    rows_per_flight = {}
    for _ in range(n):
        customer_id = random.choice(customer_ids)
        flight_id   = random.choice(flight_ids)
        # gera assento único por voo
        used = rows_per_flight.setdefault(flight_id, set())
        seat = None
        for _ in range(20):
            s = f"{random.choice('ABCDEF')}{random.randint(1,50)}"
            if s not in used:
                used.add(s)
                seat = s
                break
        if not seat:
            seat = f"X{random.randint(51,99)}"
        status = random.choice(STATUSES_RES)
        cur.execute(
            "INSERT INTO flight_reservations "
            "(customer_id, flight_id, seat_number, status) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (customer_id, flight_id, seat, status)
        )
        fr_ids.append((cur.fetchone()[0], status))
    return fr_ids


def seed_hotel_reservations(cur, customer_ids, room_ids, n=1900):
    print(f"  → Inserindo {n} reservas de hotel...")
    hr_ids = []
    for _ in range(n):
        customer_id = random.choice(customer_ids)
        room_id     = random.choice(room_ids)
        check_in, check_out = random_date_range(-365, 180)
        nights      = (check_out - check_in).days
        # busca preço do quarto
        cur.execute("SELECT price_per_night FROM rooms WHERE id = %s", (room_id,))
        price_night = float(cur.fetchone()[0])
        total       = round(price_night * nights, 2)
        status      = random.choice(STATUSES_RES)
        cur.execute(
            "INSERT INTO hotel_reservations "
            "(customer_id, room_id, check_in, check_out, status, total_price) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (customer_id, room_id, check_in, check_out, status, total)
        )
        hr_ids.append((cur.fetchone()[0], status))
    return hr_ids


def seed_payments(cur, fr_ids, hr_ids):
    print(f"  → Inserindo pagamentos...")
    count = 0
    for res_id, status in fr_ids:
        if status in ("confirmed", "cancelled"):
            cur.execute("SELECT price FROM flights f "
                        "JOIN flight_reservations fr ON fr.flight_id = f.id "
                        "WHERE fr.id = %s", (res_id,))
            row = cur.fetchone()
            if not row:
                continue
            amount = float(row[0])
            pay_status = "confirmed" if status == "confirmed" else "refunded"
            cur.execute(
                "INSERT INTO payments "
                "(reservation_type, reservation_id, amount, status, payment_method) "
                "VALUES ('flight',%s,%s,%s,%s)",
                (res_id, amount, pay_status, random.choice(PAY_METHODS))
            )
            count += 1
    for res_id, status in hr_ids:
        if status in ("confirmed", "cancelled"):
            cur.execute("SELECT total_price FROM hotel_reservations WHERE id = %s",
                        (res_id,))
            row = cur.fetchone()
            if not row:
                continue
            amount = float(row[0])
            pay_status = "confirmed" if status == "confirmed" else "refunded"
            cur.execute(
                "INSERT INTO payments "
                "(reservation_type, reservation_id, amount, status, payment_method) "
                "VALUES ('hotel',%s,%s,%s,%s)",
                (res_id, amount, pay_status, random.choice(PAY_METHODS))
            )
            count += 1
    return count


def main():
    print("BookingHub — Seed iniciado")
    print(f"Conectando em: {DATABASE_URL}")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur  = conn.cursor()

    try:
        airport_ids  = seed_airports(cur)
        hotel_ids    = seed_hotels(cur)
        room_ids     = seed_rooms(cur, hotel_ids)
        flight_ids   = seed_flights(cur, airport_ids)
        customer_ids = seed_customers(cur)
        fr_ids       = seed_flight_reservations(cur, customer_ids, flight_ids)
        hr_ids       = seed_hotel_reservations(cur, customer_ids, room_ids)
        pay_count    = seed_payments(cur, fr_ids, hr_ids)

        conn.commit()

        # Resumo
        cur.execute("""
            SELECT tablename, n_live_tup
            FROM pg_stat_user_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        # fallback: conta direto
        totais = {}
        for tbl in ["airports","hotels","rooms","flights","customers",
                    "flight_reservations","hotel_reservations","payments"]:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            totais[tbl] = cur.fetchone()[0]

        print("\n✅  Seed concluído!")
        print("-" * 40)
        total = 0
        for tbl, cnt in totais.items():
            print(f"  {tbl:<25} {cnt:>6} registros")
            total += cnt
        print("-" * 40)
        print(f"  {'TOTAL':<25} {total:>6} registros")

    except Exception as e:
        conn.rollback()
        print(f"\n❌  Erro durante o seed: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
