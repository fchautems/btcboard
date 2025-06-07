document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('dca-form');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const amount = parseFloat(document.getElementById('amount').value);
        const start = document.getElementById('start').value;
        const freq = document.getElementById('frequency').value;
        const res = await fetch('/api/dca', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, start, frequency: freq })
        });
        const data = await res.json();
        displayResults(data);
        drawDcaChart(data.progress);
    });

    fetch('/api/chart-data')
        .then(r => r.json())
        .then(drawCharts);
});

function displayResults(data) {
    const div = document.getElementById('results');
    div.innerHTML = `
    <h3>Résultats DCA</h3>
    <table class="table table-bordered">
        <tr><th>Nombre d'achats</th><td>${data.num_purchases}</td></tr>
        <tr><th>Total investi</th><td>${data.total_invested.toFixed(2)} USD</td></tr>
        <tr><th>Total BTC acheté</th><td>${data.total_btc.toFixed(6)} BTC</td></tr>
        <tr><th>Valeur finale</th><td>${data.final_value.toFixed(2)} USD</td></tr>
        <tr><th>Performance</th><td>${data.performance_pct.toFixed(2)} %</td></tr>
    </table>`;
}

function drawCharts(dataset) {
    const ctx1 = document.getElementById('priceChart').getContext('2d');
    new Chart(ctx1, {
        type: 'line',
        data: {
            labels: dataset.dates,
            datasets: [{
                label: 'BTC Price',
                data: dataset.prices,
                borderColor: 'blue',
                fill: false
            }]
        }
    });

    const ctx2 = document.getElementById('fgChart').getContext('2d');
    new Chart(ctx2, {
        type: 'line',
        data: {
            labels: dataset.dates,
            datasets: [{
                label: 'Fear & Greed',
                data: dataset.fg,
                borderColor: 'orange',
                fill: false
            }]
        }
    });
}

function drawDcaChart(progress) {
    const labels = progress.map(p => p.date);
    const values = progress.map(p => p.value);
    const ctx = document.getElementById('dcaChart').getContext('2d');
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Valeur DCA',
                data: values,
                borderColor: 'green',
                fill: false
            }]
        }
    });
}
