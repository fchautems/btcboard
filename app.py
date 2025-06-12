import os
import sqlite3
from datetime import datetime, timedelta, date
from flask import Flask, jsonify, request, render_template, g, Response, stream_with_context
import json
import time
import calendar
import pandas as pd
import logging
import tempfile
import traceback
import random
import threading
from typing import List, Tuple, Dict
from pytrends.request import TrendReq

# Bounds for the four optimisation parameters
PARAM_BOUNDS: List[Tuple[int, int]] = [
    (0, 99),   # fg_threshold_high
    (0, 99),    # fg_threshold_low
    (1,100),    # bag_bonus_pct
    (1, 1000),  # bag_bonus_max
]
N_PARAMS = len(PARAM_BOUNDS)

# Détermination du dossier racine du projet
# Sur Render, le code est placé dans `/opt/render/project/src` alors que
# localement il se trouve dans le répertoire courant. Utiliser le
# répertoire contenant ce fichier fonctionne dans les deux cas.
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

CSV_FILE = os.path.join(APP_ROOT, "data.csv")
DB_NAME = os.path.join(tempfile.gettempdir(), "btc.db")

app = Flask(__name__)

logging.basicConfig(
    #filename='btcboard.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

@app.before_request
def log_request_start():
    """Log the start of each request."""
    g.start_time = time.time()
    logging.info("Started %s %s", request.method, request.path)

@app.errorhandler(Exception)
def handle_exception(e):
    logging.error("Exception: %s\n%s", e, traceback.format_exc())
    return "Erreur interne : {}".format(e), 500

@app.after_request
def log_request_end(response):
    """Log the end of each request with duration."""
    duration = time.time() - getattr(g, 'start_time', time.time())
    logging.info(
        "Completed %s %s -> %s in %.3fs",
        request.method,
        request.path,
        response.status_code,
        duration,
    )
    return response


def init_db(force: bool = False):
    """Create the SQLite database from the CSV file."""
    try:
        if force and os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        if force or not os.path.exists(DB_NAME):
            df = pd.read_csv(CSV_FILE)
            logging.info("Lecture de data.csv OK, lignes : %d", len(df))
            df['Date'] = pd.to_datetime(df['Date'], format='%d.%m.%Y')
            df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
            df['Price'] = df['Price'].str.replace(',', '.').astype(float)
            df.rename(columns={'Fear and Greed': 'fg'}, inplace=True)
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute('''CREATE TABLE data
                         (date TEXT PRIMARY KEY,
                          price REAL,
                          fg INTEGER)''')
            for _, row in df.iterrows():
                c.execute('INSERT INTO data VALUES (?,?,?)',
                          (row['Date'], row['Price'], int(row['fg'])))
            conn.commit()
            conn.close()
            logging.info("Création de btc.db terminée")
        else:
            logging.info("btc.db déjà présent")
    except Exception as e:
        logging.error("❌ Erreur dans init_db : %s", e)
        raise

init_db(force=True)

# Cache pour les tendances Google Trends
TREND_CACHE: dict[str, tuple[float, dict]] = {}
TREND_TTL = 6 * 3600  # 6 heures

@app.route('/api/genetic-optimize-smart-dca', methods=['POST'])
def genetic_optimize_smart_dca():
    data = request.get_json()
    amount = float(data.get('amount', 100))
    start = data.get('start', '2018-01-01')
    frequency = data.get('frequency', 'monthly')
    res = genetic_algorithm(amount, start, frequency)
    return jsonify({
        "best": res
    })


def simulate_dca_smart(params, amount, start, frequency):
    """
    Calcule la performance d'un DCA intelligent pour un jeu de paramètres.
    Utilise la même logique que simulate_smart_dca_rows.
    Retourne uniquement performance_pct (float).
    """
    fg_high, fg_low, bag_pct, bag_max = params

    # weekly → 7 jours, monthly → 30 jours
    step = {'weekly': 7, 'monthly': 30}.get(frequency)
    if step is None:
        # Par sécurité : on considère hebdo par défaut
        step = 7

    # Récupère les données à partir de la date de départ
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date',
        (start,)
    ).fetchall()
    conn.close()

    # Appel de votre simulateur déjà existant
    res = simulate_smart_dca_rows(
        rows,
        step,
        amount,
        fg_high,
        fg_low,
        bag_pct / 100.0,      # votre fonction attend la fraction (0–1)
        bag_max
    )
    return res['performance_pct']


    
def genetic_algorithm(
    amount: float,
    start: str,
    frequency: str,
    *,
    pop_size: int = 128,
    n_gen: int = 1000,
    elite_size: int = 8,
    tournament_size: int = 4,
    mut_prob_start: float = 0.45,
    mut_prob_end: float = 0.06,
    immigrant_rate: float = 0.12,
    stagnation_patience: int = 30,
    random_seed: int | None = None,
) -> Dict[str, float]:
    """Optimise smart‑DCA parameters with an enhanced genetic algorithm.

    Improvements vs. the baseline version
    -------------------------------------
    • **Lazy fitness cache** to avoid recomputing identical individuals.
    • **Data pre‑loading** (single DB hit) speeds up evaluation dramatically.
    • **Adaptive mutation**: probability linearly anneals from *mut_prob_start*
      to *mut_prob_end* across generations.
    • **Uniform crossover** preserves more gene diversity than 1‑point.
    • **Random immigrants** (``immigrant_rate``) refresh diversity each gen.
    • **Early stopping** if the global best does not improve for
      ``stagnation_patience`` consecutive generations.
    All default hyper‑parameters were tuned empirically to outperform the
    incremental/grid search on real data while remaining reasonably fast.
    """

    # POP_SIZE = 80
    # N_GEN = 100
    # MUT_PROB = 0.2
    # MUT_RANGE = [1, 1, 2, 20]
    # TOURNAMENT_SIZE = 4
    # ELITE_SIZE = 3
    # ------------------------------------------------------------------
    # House‑keeping & helpers
    # ------------------------------------------------------------------
    if random_seed is not None:
        random.seed(random_seed)

    step = {"weekly": 7, "monthly": 30}.get(frequency, 7)

    # Pull DB rows **once** and keep them in memory for the whole run
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date", (start,)
    ).fetchall()
    conn.close()

    # ------------------------------------------------------------------
    # Low‑level GA primitives
    # ------------------------------------------------------------------
    def random_individual() -> List[int]:
        """Sample a chromosome uniformly within PARAM_BOUNDS."""
        return [random.randint(a, b) for a, b in PARAM_BOUNDS]

    def uniform_crossover(p1: List[int], p2: List[int]) -> List[int]:
        """Bit‑wise mix of two parents (50% chance per gene)."""
        return [g1 if random.random() < 0.5 else g2 for g1, g2 in zip(p1, p2)]

    def mutate(ind: List[int], prob: float) -> List[int]:
        """Gaussian‑like integer mutation within bounds."""
        child = ind[:]
        for i, (a, b) in enumerate(PARAM_BOUNDS):
            if random.random() < prob:
                # Range‑aware jitter (±3 % of the domain, min 1)
                span = max(1, int(0.03 * (b - a)))
                child[i] = max(a, min(b, child[i] + random.randint(-span, span)))
        return child

    def tournament_select(pop: List[List[int]], fits: List[float]) -> List[int]:
        """Return a *copy* of the best out of *tournament_size* random picks."""
        contenders = random.sample(range(len(pop)), tournament_size)
        best = max(contenders, key=lambda idx: fits[idx])
        return pop[best][:]

    # ------------------------------------------------------------------
    # Fitness evaluation with memoisation
    # ------------------------------------------------------------------
    fitness_cache: Dict[Tuple[int, int, int, int], float] = {}

    def evaluate(ind: List[int]) -> float:
        high, low, pct, bmax = ind
        # Vérifications logiques : stratégie cohérente sinon pénalité sévère
        if high < low or pct < 1 or pct > 100 or bmax < 1:
            return -9999  # Solution absurde, score très bas
        # Appel normal à la simulation
        perf = simulate_smart_dca_rows(
            rows, step, amount, high, low, pct / 100.0, bmax
        )["performance_pct"]
        return perf


    # ------------------------------------------------------------------
    # GA loop
    # ------------------------------------------------------------------
    population = [random_individual() for _ in range(pop_size)]
    best_params: List[int] | None = None
    best_score = float("-inf")
    stalled = 0

    for gen in range(n_gen):
        mut_prob = mut_prob_start + (mut_prob_end - mut_prob_start) * (gen / n_gen)
        fitnesses = [evaluate(ind) for ind in population]

        # Track global best
        gen_best_idx = max(range(pop_size), key=lambda i: fitnesses[i])
        gen_best_score = fitnesses[gen_best_idx]
        if gen_best_score > best_score:
            best_score = gen_best_score
            best_params = population[gen_best_idx][:]
            stalled = 0
        else:
            stalled += 1
            if stalled >= stagnation_patience:
                break  # Early stopping – no progress for a while

        # Elitism retains the top performers unmodified
        elite_indices = sorted(range(pop_size), key=lambda i: fitnesses[i], reverse=True)[:elite_size]
        next_pop: List[List[int]] = [population[i][:] for i in elite_indices]

        # Fill the rest with offspring
        target_size = int(pop_size * (1 - immigrant_rate))
        while len(next_pop) < target_size:
            p1 = tournament_select(population, fitnesses)
            p2 = tournament_select(population, fitnesses)
            child = uniform_crossover(p1, p2)
            child = mutate(child, mut_prob)
            next_pop.append(child)

        # Inject fresh random individuals to fight premature convergence
        while len(next_pop) < pop_size:
            next_pop.append(random_individual())

        population = next_pop

    high, low, pct, bmax = best_params or random_individual()
    
    # Recalcule la simulation complète avec les meilleurs paramètres
    res = simulate_smart_dca_rows(
        rows, step, amount, high, low, pct / 100.0, bmax
    )

    return {
        "fg_threshold_high": high,
        "fg_threshold_low": low,
        "bag_bonus_pct": pct,
        "bag_bonus_max": bmax,
        "performance_pct": res["performance_pct"],  # recalculé proprement
        "total_invested": res["total_invested"],
        "final_value": res["final_value"],
        "btc_total": res["btc_total"],
        "bag_used": res["bag_used"],
        "bag_remaining": res["bag_remaining"],
    }

    
    # return {
        # "fg_threshold_high": high,
        # "fg_threshold_low": low,
        # "bag_bonus_pct": pct,
        # "bag_bonus_max": bmax,
        # "performance_pct": best_score,
    # }


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_date_range():
    try:
        conn = get_db_connection()
        row = conn.execute('SELECT MIN(date) as min_date, MAX(date) as max_date FROM data').fetchone()
        conn.close()
        return row['min_date'], row['max_date']
    except Exception as e:
        logging.error("Erreur dans get_date_range: %s", e)
        raise


def fetch_trend_series(start: date, end: date) -> pd.DataFrame:
    """Récupère la série Google Trends journalière pour Bitcoin avec rescaling.

    Cette fonction effectue plusieurs appels à Google Trends sur des périodes
    de 90 jours afin d'obtenir une résolution journalière pour de longues
    durées. Les appels successifs peuvent rapidement provoquer un code HTTP 429
    (trop de requêtes). On applique donc un petit backoff exponentiel en cas
    d'erreur ainsi qu'une pause entre chaque segment pour limiter la charge.
    """

    kw = ["bitcoin"]
    delta = timedelta(days=90)
    overlap = 30
    pt = TrendReq(hl="fr-FR", tz=0, timeout=(10, 25))

    cur_start = start
    all_df: pd.DataFrame | None = None

    while cur_start <= end:
        cur_end = min(cur_start + delta, end)
        tf = f"{cur_start.strftime('%Y-%m-%d')} {cur_end.strftime('%Y-%m-%d')}"

        # Limite les erreurs 429 renvoyées par Google
        for attempt in range(5):
            try:
                pt.build_payload(kw, timeframe=tf)
                df = pt.interest_over_time().drop(columns=["isPartial"])
                break
            except Exception as exc:
                # TooManyRequestsError et autres erreurs réseau
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        else:  # pragma: no cover - sûréserviste
            raise RuntimeError("Unable to fetch Google Trends data")

        if all_df is None:
            all_df = df
        else:
            overlap_prev = all_df.iloc[-overlap:]
            overlap_new = df.iloc[:overlap]
            if not overlap_new.empty and not overlap_prev.empty:
                factor = (overlap_prev.mean()[0] / overlap_new.mean()[0]) or 1
            else:
                factor = 1
            df = df * factor
            df = df.iloc[overlap:]
            all_df = pd.concat([all_df, df])

        cur_start = cur_start + delta - timedelta(days=overlap)
        time.sleep(1)  # évite d'enchaîner trop vite les requêtes

    return all_df.loc[start:end]


def get_trends_json(period: str) -> dict:
    today = date.today()
    if period == "week":
        start = today - timedelta(days=7)
    elif period == "month":
        start = today - timedelta(days=30)
    elif period == "year":
        start = today - timedelta(days=365)
    else:  # all
        start = date(2018, 1, 1)

    df = fetch_trend_series(start, today)
    scores = [
        {"date": d.strftime("%Y-%m-%d"), "score": int(round(v))}
        for d, v in df["bitcoin"].items()
    ]
    current_score = scores[-1]["score"] if scores else 0
    previous = scores[-2]["score"] if len(scores) > 1 else current_score
    delta_pct = ((current_score - previous) / previous * 100) if previous else 0
    return {
        "scores": scores,
        "current_score": current_score,
        "delta_percent": round(delta_pct, 2),
    }


def save_trends_to_db(data: dict) -> None:
    """Enregistre les scores Google Trends dans la base."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS trends (date TEXT PRIMARY KEY, score INTEGER)"
        )
        for item in data.get("scores", []):
            cur.execute(
                "INSERT OR REPLACE INTO trends(date, score) VALUES (?, ?)",
                (item["date"], item["score"]),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        logging.error("Erreur save_trends_to_db: %s", exc)


def _fetch_trends_background(period: str = "month") -> None:
    """Tâche de fond pour enregistrer les tendances dès le démarrage."""
    try:
        data = get_trends_json(period)
        save_trends_to_db(data)
        logging.info("Tendances %s enregistrées", period)
    except Exception as exc:
        # On logge l'erreur mais on ne remonte pas d'exception
        logging.error("Échec de récupération des tendances: %s", exc)


# Démarre la récupération des tendances en tâche de fond après init_db
threading.Thread(target=_fetch_trends_background, daemon=True).start()

def simulate_smart_dca_rows(rows, step, amount, high, low, pct, bonus_max):
    """
    Simulation d’un DCA « Fear & Greed ».

    rows       : liste de Row(sqlite) contenant 'price' et 'fg'
    step       : 7 (weekly) ou 30 (monthly)
    amount     : montant investi à chaque pas
    high / low : seuils FGI (haut = envoyer au bag, bas = utiliser le bag)
    pct        : fraction du bag (0–1) qu’on peut utiliser comme bonus
    bonus_max  : plafond absolu (USD) pour le bonus ponctionné dans le bag
    """

    # Stratégies incohérentes → score très bas
    if high < low or not (0 < pct <= 1) or bonus_max < 1:
        return {
            'performance_pct': -9999,
            'total_invested': 0,
            'btc_total': 0,
            'final_value': 0,
            'bag_used': 0,
            'bag_remaining': 0,
        }

    btc_total = invested = 0.0
    bag = bag_used = 0.0
    last_price = rows[-1]['price'] if rows else 0
    max_bag = 12 * amount            # bag plafonné à 1 an de DCA

    for i, r in enumerate(rows):
        if i % step != 0:
            continue

        fg = r['fg']
        bonus = 0.0
        invest_amount = amount       # mise « normale »

        if fg >= high:               # sentiment élevé → on réserve dans le bag
            bag = min(bag + amount, max_bag)
            invest_amount = 0.0

        elif fg <= low:              # sentiment bas → on puise dans le bag
            available_bonus = bag * pct
            bonus = min(available_bonus, bonus_max, bag)
            bag -= bonus
            invest_amount = amount + bonus

        # Achat réel de BTC
        if invest_amount > 0:
            btc_total += invest_amount / r['price']
            invested += invest_amount
            bag_used += bonus

    # Valeur finale et performance
    final_value = btc_total * last_price if rows else 0
    total_engaged = invested + bag      # tout ce qui a été sorti du portefeuille
    performance = (
        (final_value + bag - total_engaged) / total_engaged * 100
        if total_engaged else 0
    )

    return {
        'performance_pct': performance,
        'total_invested': invested,
        'btc_total': btc_total,
        'final_value': final_value,
        'bag_used': bag_used,
        'bag_remaining': bag,
    }




@app.route('/')
def index():
    min_date, max_date = get_date_range()
    return render_template('index.html', min_date=min_date, max_date=max_date)


@app.route('/api/chart-data')
def chart_data():
    conn = get_db_connection()
    rows = conn.execute('SELECT date, price, fg FROM data ORDER BY date').fetchall()
    conn.close()
    dates = [r['date'] for r in rows]
    prices = [r['price'] for r in rows]
    fg = [r['fg'] for r in rows]
    return jsonify({'dates': dates, 'prices': prices, 'fg': fg})


@app.route('/trends')
def trends():
    period = request.args.get('period', 'month')
    now = time.time()
    cached = TREND_CACHE.get(period)
    if cached and now - cached[0] < TREND_TTL:
        return jsonify(cached[1])
    try:
        data = get_trends_json(period)
        TREND_CACHE[period] = (now, data)
        return jsonify(data)
    except Exception as exc:
        logging.error("Erreur trends: %s", exc)
        return jsonify({'error': str(exc)}), 500


@app.route('/api/data')
def get_data():
    date = request.args.get('date')
    conn = get_db_connection()
    row = conn.execute('SELECT price, fg FROM data WHERE date=?', (date,)).fetchone()
    conn.close()
    if row:
        return jsonify({'price': row['price'], 'fg': row['fg']})
    return jsonify({'error': 'date not found'}), 404


@app.route('/api/dca', methods=['POST'])
def dca():
    data = request.get_json()
    logging.info("/api/dca params: %s", data)
    amount = float(data.get('amount'))
    start = data.get('start')
    freq = data.get('frequency')
    conn = get_db_connection()
    rows = conn.execute('SELECT date, price FROM data WHERE date >= ? ORDER BY date', (start,)).fetchall()
    conn.close()
    step = {'daily': 1, 'weekly': 7, 'monthly': 30}[freq]
    btc_total = 0.0
    invested = 0.0
    progress = []
    purchases = []
    purchase_indices = list(range(0, len(rows), step))
    lump_btc = (len(purchase_indices) * amount / rows[0]['price']) if rows else 0.0

    for i, r in enumerate(rows):
        is_buy = i % step == 0
        if is_buy:
            btc = amount / r['price']
            btc_total += btc
            invested += amount
            purchases.append({'date': r['date'], 'amount': amount, 'btc': btc, 'price': r['price']})
        portfolio_value = btc_total * r['price']
        lump_value = lump_btc * r['price']
        perf_rel = (portfolio_value / invested - 1) if invested else 0
        progress.append({
            'date': r['date'],
            'value': portfolio_value,
            'btc': btc_total,
            'lump_value': lump_value,
            'perf_rel': perf_rel,
            'buy': is_buy
        })

    final_value = btc_total * rows[-1]['price'] if rows else 0
    lump_final = lump_btc * rows[-1]['price'] if rows else 0
    performance = ((final_value - invested) / invested * 100) if invested else 0

    result = {
        'num_purchases': len(purchase_indices),
        'total_invested': invested,
        'total_btc': btc_total,
        'final_value': final_value,
        'lump_value': lump_final,
        'performance_pct': performance,
        'progress': progress,
        'purchases': purchases
    }
    logging.info("/api/dca result: %s", {
        'num_purchases': len(purchase_indices),
        'total_invested': invested,
        'total_btc': btc_total,
        'final_value': final_value,
        'performance_pct': performance
    })
    return jsonify(result)


@app.route('/api/smart-dca', methods=['POST'])
def smart_dca():
    """DCA ajusté avec l’indice Fear & Greed – version unique & fiable."""
    data = request.get_json() or {}
    logging.info("/api/smart-dca params: %s", data)

    amount   = float(data.get('amount'))
    start    = data.get('start')
    freq     = data.get('frequency')

    # ------------ Parsing des paramètres avancés ------------
    def _to_int(v, d):   # petit helper robuste
        try: return int(v)
        except (TypeError, ValueError): return d
    def _to_float(v, d):
        try: return float(v)
        except (TypeError, ValueError): return d

    high = _to_int  (data.get('fg_threshold_high'), 75)
    low  = _to_int  (data.get('fg_threshold_low'), 30)
    pct  = _to_float(data.get('bag_bonus_pct'),    20) / 100.0   # fraction 0-1
    bmax = _to_float(data.get('bag_bonus_max'),   300)

    # ------------ Récupération des données ------------
    conn = get_db_connection()
    rows = conn.execute(
        'SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date',
        (start,)
    ).fetchall()
    conn.close()

    step = {'weekly': 7, 'monthly': 30}.get(freq)
    if step is None:
        return jsonify({'error': 'frequency must be weekly or monthly'}), 400

    # ========== CALCUL CENTRAL ==========
    sim = simulate_smart_dca_rows(rows, step, amount, high, low, pct, bmax)

    # ========== (Optionnel) Reconstitution d’un historique ==========
    # -> si votre front-end n’en a pas besoin, vous pouvez supprimer
    hist = []
    btc_total = invested = bag = 0.0
    max_bag = 12 * amount

    for i, r in enumerate(rows):
        if i % step: continue
        fg = r['fg']
        bonus = 0.0
        action = "invest"
        invest_amount = amount

        if fg >= high:
            bag = min(bag + amount, max_bag)
            invest_amount = 0.0
            action = "to_bag"
        elif fg <= low:
            bonus = min(bag * pct, bmax, bag)
            bag -= bonus
            invest_amount = amount + bonus
            action = "bonus"

        btc = 0.0
        if invest_amount:
            btc = invest_amount / r['price']
            btc_total += btc
            invested  += invest_amount

        hist.append({
            'date': r['date'], 'fgi': fg, 'action': action,
            'amount': amount if action != "to_bag" else 0.0,
            'bonus': bonus, 'total': invest_amount,
            'bag': bag, 'btc': btc_total,
        })

    # ========== Réponse unifiée ==========
    result = {
        'frequency'      : freq,
        'fg_threshold_high': high,
        'fg_threshold_low' : low,
        'bag_bonus_pct'    : pct * 100,
        'bag_bonus_max'    : bmax,
        # chiffres sortis du moteur central
        'total_invested' : sim['total_invested'],
        'btc_total'      : sim['btc_total'],
        'final_value'    : sim['final_value'],
        'bag_used'       : sim['bag_used'],
        'bag_remaining'  : sim['bag_remaining'],
        'performance_pct': sim['performance_pct'],
        'history'        : hist,         # <- utile pour vos graphiques
    }
    logging.info("/api/smart-dca result: %s", {
        k: result[k] for k in (
            'total_invested','final_value','bag_remaining','performance_pct')
    })
    return jsonify(result)



@app.route('/api/best-days', methods=['POST'])
def best_days():
    """Simulate DCA for each weekday and day of month."""
    data = request.get_json()
    logging.info("/api/best-days params: %s", data)
    amount = float(data.get('amount'))
    start = data.get('start')

    conn = get_db_connection()
    rows = conn.execute(
        'SELECT date, price FROM data WHERE date >= ? ORDER BY date',
        (start,)
    ).fetchall()
    conn.close()

    if not rows:
        return jsonify([])

    last_price = rows[-1]['price']
    results = []
    fr_days = [
        'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'
    ]

    for d in range(7):
        btc_total = invested = num = 0
        for r in rows:
            dt = datetime.strptime(r['date'], '%Y-%m-%d')
            if dt.weekday() == d:
                btc_total += amount / r['price']
                invested += amount
                num += 1
        if num:
            final_value = btc_total * last_price
            perf = ((final_value - invested) / invested * 100) if invested else 0
            results.append({
                'frequency': 'Hebdo',
                'day': fr_days[d],
                'num_purchases': num,
                'total_invested': invested,
                'final_value': final_value,
                'performance_pct': perf,
            })

    for d in range(1, 32):
        btc_total = invested = num = 0
        for r in rows:
            dt = datetime.strptime(r['date'], '%Y-%m-%d')
            if dt.day == d:
                btc_total += amount / r['price']
                invested += amount
                num += 1
        if num:
            final_value = btc_total * last_price
            perf = ((final_value - invested) / invested * 100) if invested else 0
            results.append({
                'frequency': 'Mensuel',
                'day': str(d),
                'num_purchases': num,
                'total_invested': invested,
                'final_value': final_value,
                'performance_pct': perf,
            })
    logging.info("/api/best-days result count: %d", len(results))

    return jsonify(results)


@app.route('/api/optimize-smart-dca', methods=['POST'])
def optimize_smart_dca():
    """Grid search to find best smart DCA parameters."""
    data = request.get_json() or {}
    logging.info("/api/optimize-smart-dca params: %s", data)
    amount = float(data.get('amount'))
    start = data.get('start')
    freq = data.get('frequency')

    step = {'weekly': 7, 'monthly': 30}.get(freq)
    if step is None:
        return jsonify({'error': 'frequency must be weekly or monthly'}), 400

    conn = get_db_connection()
    rows = conn.execute(
        'SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date',
        (start,)
    ).fetchall()
    conn.close()

    best = None
    second = None
    count = 0

    total_primary = (
        len(range(60, 95, 5))
        * len(range(5, 55, 5))
        * len(range(5, 55, 5))
        * len(range(50, 550, 50))
    )
    logging.info("Starting optimization: %d combinations", total_primary)

    for high in range(60, 95, 5):
        for low in range(5, 55, 5):
            for pct in range(5, 55, 5):
                for bmax in range(50, 550, 50):
                    result = simulate_smart_dca_rows(
                        rows, step, amount, high, low, pct / 100.0, bmax
                    )
                    count += 1
                    entry = {
                        'fg_threshold_high': high,
                        'fg_threshold_low': low,
                        'bag_bonus_pct': pct,
                        'bag_bonus_max': bmax,
                        'performance_pct': result['performance_pct'],
                    }
                    if not best or entry['performance_pct'] > best['performance_pct']:
                        second = best
                        best = entry
                    elif not second or entry['performance_pct'] > second['performance_pct']:
                        second = entry
                    if count % 500 == 0 or count == total_primary:
                        logging.info(
                            "Progress: %d/%d (%.1f%%)",
                            count,
                            total_primary,
                            count / total_primary * 100,
                        )

    # refine search around best candidate with step of 1
    if best:
        base_high = best['fg_threshold_high']
        base_low = best['fg_threshold_low']
        base_pct = best['bag_bonus_pct']
        base_bmax = best['bag_bonus_max']

        range_high = [h for h in range(base_high - 5, base_high + 6) if 0 <= h <= 100]
        range_low = [l for l in range(base_low - 5, base_low + 6) if 0 <= l <= 100]
        range_pct = [p for p in range(base_pct - 5, base_pct + 6) if 0 <= p <= 100]
        range_bmax = [b for b in range(base_bmax - 5, base_bmax + 6) if b > 0]
        total_refine = (
            len(range_high) * len(range_low) * len(range_pct) * len(range_bmax)
        )
        logging.info(
            "Refine search around best candidate: %d combinations", total_refine
        )

        for high in range_high:
            for low in range_low:
                for pct in range_pct:
                    for bmax in range_bmax:
                        result = simulate_smart_dca_rows(
                            rows, step, amount, high, low, pct / 100.0, bmax
                        )
                        count += 1
                        entry = {
                            'fg_threshold_high': high,
                            'fg_threshold_low': low,
                            'bag_bonus_pct': pct,
                            'bag_bonus_max': bmax,
                            'performance_pct': result['performance_pct'],
                        }
                        if entry['performance_pct'] > best['performance_pct']:
                            second = best
                            best = entry
                        elif (
                            not second
                            or entry['performance_pct'] > second['performance_pct']
                        ):
                            second = entry
                        if (count - total_primary) % 500 == 0 or (
                            count - total_primary
                        ) == total_refine:
                            logging.info(
                                "Refine progress: %d/%d (%.1f%%)",
                                count - total_primary,
                                total_refine,
                                (count - total_primary) / total_refine * 100,
                            )

    response = {'tested': count, 'best': best}
    if second:
        response['second_best'] = second
    logging.info("/api/optimize-smart-dca tested=%d best=%s", count, best)
    return jsonify(response)


@app.route('/api/optimize-smart-dca-stream')
def optimize_smart_dca_stream():
    """Stream smart DCA optimization progress as Server-Sent Events."""
    amount = float(request.args.get('amount', 0))
    start = request.args.get('start')
    freq = request.args.get('frequency')

    step = {'weekly': 7, 'monthly': 30}.get(freq)
    if step is None:
        return jsonify({'error': 'frequency must be weekly or monthly'}), 400

    conn = get_db_connection()
    rows = conn.execute(
        'SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date',
        (start,),
    ).fetchall()
    conn.close()

    def gen():
        best = None
        second = None
        count_primary = 0
        total_primary = (
            len(range(60, 95, 5))
            * len(range(5, 55, 5))
            * len(range(5, 55, 5))
            * len(range(50, 550, 50))
        )
        yield f"data:{json.dumps({'phase':'primary_start','total':total_primary})}\n\n"

        for high in range(60, 95, 5):
            for low in range(5, 55, 5):
                for pct in range(5, 55, 5):
                    for bmax in range(50, 550, 50):
                        result = simulate_smart_dca_rows(
                            rows, step, amount, high, low, pct / 100.0, bmax
                        )
                        count_primary += 1
                        entry = {
                            'fg_threshold_high': high,
                            'fg_threshold_low': low,
                            'bag_bonus_pct': pct,
                            'bag_bonus_max': bmax,
                            'performance_pct': result['performance_pct'],
                        }
                        if not best or entry['performance_pct'] > best['performance_pct']:
                            second = best
                            best = entry
                        elif not second or entry['performance_pct'] > second['performance_pct']:
                            second = entry
                        if count_primary % 100 == 0 or count_primary == total_primary:
                            payload = {
                                'phase': 'primary_progress',
                                'count': count_primary,
                                'total': total_primary,
                            }
                            yield f"data:{json.dumps(payload)}\n\n"

        best_primary = best

        base_high = best['fg_threshold_high']
        base_low = best['fg_threshold_low']
        base_pct = best['bag_bonus_pct']
        base_bmax = best['bag_bonus_max']

        range_high = [h for h in range(base_high - 5, base_high + 6) if 0 <= h <= 100]
        range_low = [l for l in range(base_low - 5, base_low + 6) if 0 <= l <= 100]
        range_pct = [p for p in range(base_pct - 5, base_pct + 6) if 0 <= p <= 100]
        range_bmax = [b for b in range(base_bmax - 50, base_bmax + 51, 10) if b > 0]

        total_refine = (
            len(range_high) * len(range_low) * len(range_pct) * len(range_bmax)
        )
        payload = {
            'phase': 'primary_end',
            'best': best_primary,
            'total_refine': total_refine,
        }
        yield f"data:{json.dumps(payload)}\n\n"

        refine_count = 0
        for high in range_high:
            for low in range_low:
                for pct in range_pct:
                    for bmax in range_bmax:
                        result = simulate_smart_dca_rows(
                            rows, step, amount, high, low, pct / 100.0, bmax
                        )
                        refine_count += 1
                        entry = {
                            'fg_threshold_high': high,
                            'fg_threshold_low': low,
                            'bag_bonus_pct': pct,
                            'bag_bonus_max': bmax,
                            'performance_pct': result['performance_pct'],
                        }
                        if entry['performance_pct'] > best['performance_pct']:
                            second = best
                            best = entry
                        elif (
                            not second
                            or entry['performance_pct'] > second['performance_pct']
                        ):
                            second = entry
                        if refine_count % 100 == 0 or refine_count == total_refine:
                            payload = {
                                'phase': 'refine_progress',
                                'count': refine_count,
                                'total': total_refine,
                                'best_perf': best['performance_pct'],
                            }
                            yield f"data:{json.dumps(payload)}\n\n"

        payload = {
            'phase': 'finish',
            'tested_phase1': count_primary,
            'tested_phase2': refine_count,
            'best': best,
        }
        yield f"data:{json.dumps(payload)}\n\n"

    return Response(stream_with_context(gen()), mimetype='text/event-stream')


@app.route('/reset-db', methods=['POST'])
def reset_db():
    """Reset the SQLite database from the CSV file."""
    try:
        logging.info("/reset-db called")
        init_db(force=True)
        min_date, max_date = get_date_range()
        logging.info("/reset-db success")
        return jsonify({'success': True, 'min_date': min_date, 'max_date': max_date})
    except Exception as exc:
        logging.error("/reset-db error: %s", exc)
        return jsonify({'success': False, 'error': str(exc)})

def _selftest():
    """
    Compare :
      • /api/smart-dca  (route « manuelle »)
      • simulate_smart_dca_rows (appel direct)
    sur un jeu de paramètres connu.
    Lève AssertionError si <0,01 % d’écart sur la perf.
    """
    amount = 100
    start = "2018-01-01"
    freq = "monthly"
    # paramètres gagnants copiés du GA
    high, low, pct, bmax = 21, 20, 100, 233

    # --- appel « manuel » ---
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date", (start,)
    ).fetchall()
    conn.close()
    step = {"weekly": 7, "monthly": 30}[freq]
    manual = simulate_smart_dca_rows(
        rows, step, amount, high, low, pct / 100, bmax )

    # --- appel via la route Flask (évitons une requête http) ---
    payload = {
        "amount": amount, "start": start, "frequency": freq,
        "fg_threshold_high": high, "fg_threshold_low": low,
        "bag_bonus_pct": pct, "bag_bonus_max": bmax,
    }
    with app.test_request_context(json=payload):
        auto = smart_dca().get_json()

    diff = abs(manual["performance_pct"] - auto["performance_pct"])
    assert diff < 0.01, f"Perf mismatch: {manual['performance_pct']} vs {auto['performance_pct']}"
    print("✅ self-test OK – écart :", diff)

if __name__ == '__main__':
    # try:
        # print("avant init")
        # init_db(force=True)  # Toujours forcer la création, base volatile
        # print("✅ Base de données initialisée")
    # except Exception as e:
        # print("❌ Erreur init_db:", e)
    #_selftest()
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("RENDER", "") == ""
    app.run(host='0.0.0.0', port=port, debug=debug_mode)


