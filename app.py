import os
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, request, render_template, g, Response, stream_with_context
import json
import time
import calendar
import pandas as pd
import logging
import tempfile
import traceback

import os
import tempfile

# Détermination du dossier racine du projet
# Sur Render, le code est placé dans `/opt/render/project/src` alors que
# localement il se trouve dans le répertoire courant. Utiliser le
# répertoire contenant ce fichier fonctionne dans les deux cas.
APP_ROOT = os.path.dirname(os.path.abspath(__file__))

CSV_FILE = os.path.join(APP_ROOT, "data.csv")
DB_NAME = os.path.join(tempfile.gettempdir(), "btc.db")


print("=== DEBUG CHEMINS ===")
print("APP_ROOT :", APP_ROOT)
print("DB_NAME  :", DB_NAME)
print("CSV_FILE :", CSV_FILE)
print("=====================")

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
    print("on est dedans")
    """Create the SQLite database from the CSV file."""
    try:
        print(f"Chemin absolu de data.csv : {CSV_FILE}")
        print(f"Chemin absolu de la base : {DB_NAME}")
        if force and os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        if force or not os.path.exists(DB_NAME):
            df = pd.read_csv(CSV_FILE)
            print("Lecture de data.csv OK, lignes :", len(df))
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
            print("Création de btc.db terminée")
        else:
            print("btc.db déjà présent")
    except Exception as e:
        print("❌ Erreur dans init_db :", e)
        raise

init_db(force=True)


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

def simulate_smart_dca_rows(rows, step, amount, high, low, pct, bonus_max):
    """Run smart DCA simulation on given rows and return summary metrics."""
    btc_total = invested = 0.0
    bag = bag_used = 0.0
    last_price = rows[-1]['price'] if rows else 0

    for i, r in enumerate(rows):
        if i % step != 0:
            continue
        fg = r['fg']
        bonus = 0.0
        invest_amount = amount
        if fg >= high:
            bag += amount
            invest_amount = 0.0
        elif fg <= low:
            bonus = min(bag * pct, bonus_max)
            bag -= bonus
            invest_amount = amount + bonus

        if invest_amount > 0:
            btc_total += invest_amount / r['price']
            invested += invest_amount
            bag_used += bonus

    final_value = btc_total * last_price if rows else 0
    performance = ((final_value - invested) / invested * 100) if invested else 0

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
    """DCA adjusted using Fear & Greed Index."""
    data = request.get_json() or {}
    logging.info("/api/smart-dca params: %s", data)
    amount = float(data.get('amount'))
    start = data.get('start')
    freq = data.get('frequency')

    def parse_int(val, default):
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def parse_float(val, default):
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    fgi_threshold_high = parse_int(data.get('fg_threshold_high'), 75)
    fgi_threshold_low = parse_int(data.get('fg_threshold_low'), 30)
    bonus_from_bag_pct = parse_float(data.get('bag_bonus_pct'), 20) / 100
    max_bonus_from_bag = parse_float(data.get('bag_bonus_max'), 300)

    conn = get_db_connection()
    rows = conn.execute('SELECT date, price, fg FROM data WHERE date >= ? ORDER BY date', (start,)).fetchall()
    conn.close()

    step = {'weekly': 7, 'monthly': 30}.get(freq)
    if step is None:
        return jsonify({'error': 'frequency must be weekly or monthly'}), 400

    btc_total = invested = 0.0
    bag = bag_used = 0.0
    history = []

    last_price = rows[-1]['price'] if rows else 0

    for i, r in enumerate(rows):
        if i % step != 0:
            continue
        fg = r['fg']
        bonus = 0.0
        action = "invest"
        invest_amount = amount
        if fg >= fgi_threshold_high:
            bag += amount
            action = "to_bag"
            invest_amount = 0.0
        elif fg <= fgi_threshold_low:
            bonus = min(bag * bonus_from_bag_pct, max_bonus_from_bag)
            bag -= bonus
            invest_amount = amount + bonus
            action = "bonus"

        btc = 0.0
        if invest_amount > 0:
            btc = invest_amount / r['price']
            btc_total += btc
            invested += invest_amount
            bag_used += bonus

        history.append({
            'date': r['date'],
            'fgi': fg,
            'action': action,
            'amount': amount if action != 'to_bag' else 0.0,
            'bonus': bonus,
            'total': invest_amount,
            'bag': bag,
            'btc': btc,
        })

        logging.info(
            "date=%s fg=%s action=%s invest=%.2f bonus=%.2f bag=%.2f btc=%.8f",
            r['date'], fg, action, amount, bonus, bag, btc_total
        )

    final_value = btc_total * last_price if rows else 0
    performance = ((final_value - invested) / invested * 100) if invested else 0

    result = {
        'frequency': freq,
        'total_invested': invested,
        'btc_total': btc_total,
        'final_value': final_value,
        'bag_used': bag_used,
        'bag_remaining': bag,
        'performance_pct': performance,
        'history': history,
    }
    logging.info("/api/smart-dca result: %s", {
        'total_invested': invested,
        'btc_total': btc_total,
        'final_value': final_value,
        'bag_used': bag_used,
        'bag_remaining': bag,
        'performance_pct': performance,
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
            'count_primary': count_primary,
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
            'best_initial_perf': best_primary['performance_pct'],
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


if __name__ == '__main__':
    # try:
        # print("avant init")
        # init_db(force=True)  # Toujours forcer la création, base volatile
        # print("✅ Base de données initialisée")
    # except Exception as e:
        # print("❌ Erreur init_db:", e)

    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("RENDER", "") == ""
    app.run(host='0.0.0.0', port=port, debug=debug_mode)


