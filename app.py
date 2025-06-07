import os
import sqlite3
from datetime import datetime
from flask import Flask, jsonify, request, render_template
import pandas as pd

DB_NAME = 'btc.db'
CSV_FILE = 'data.csv'

app = Flask(__name__)


def init_db():
    if not os.path.exists(DB_NAME):
        df = pd.read_csv(CSV_FILE)
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


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def index():
    return render_template('index.html')


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
    amount = float(data.get('amount'))
    start = data.get('start')
    freq = data.get('frequency')
    conn = get_db_connection()
    rows = conn.execute('SELECT date, price FROM data WHERE date >= ? ORDER BY date', (start,)).fetchall()
    conn.close()
    step = {'daily':1, 'weekly':7, 'monthly':30}[freq]
    btc_total = 0.0
    invested = 0.0
    progress = []
    for i in range(0, len(rows), step):
        r = rows[i]
        btc = amount / r['price']
        btc_total += btc
        invested += amount
        portfolio_value = btc_total * rows[-1]['price']
        progress.append({'date': r['date'], 'value': portfolio_value})
    final_value = btc_total * rows[-1]['price'] if rows else 0
    performance = ((final_value - invested) / invested * 100) if invested else 0
    result = {
        'num_purchases': len(progress),
        'total_invested': invested,
        'total_btc': btc_total,
        'final_value': final_value,
        'performance_pct': performance,
        'progress': progress
    }
    return jsonify(result)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
