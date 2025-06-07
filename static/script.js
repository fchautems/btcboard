document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('dca-form');
    const calcBtn = form.querySelector('button[type="submit"]');
    const calcSpinner = document.getElementById('calc-spinner');
    const exportBtn = document.getElementById('export-btn');
    const resetBtn = document.getElementById('reset-btn');
    const resetSpinner = document.getElementById('reset-spinner');
    const resetMsg = document.getElementById('reset-msg');
    const bestBtn = document.getElementById('best-days-btn');
    const bestSpinner = document.getElementById('best-spinner');
    const bestDiv = document.getElementById('best-days');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        calcBtn.disabled = true;
        calcSpinner.classList.remove('d-none');
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
        drawBtcChart(data.progress);
        drawPerfChart(data.progress);
        exportBtn.classList.remove('d-none');
        exportBtn.onclick = () => exportCsv(data.purchases);
        calcSpinner.classList.add('d-none');
        calcBtn.disabled = false;
    });

    fetch('/api/chart-data')
        .then(r => r.json())
        .then(drawCharts);

    bestBtn.addEventListener('click', async () => {
        bestBtn.disabled = true;
        bestSpinner.classList.remove('d-none');
        bestDiv.innerHTML = '<em>Calcul en cours...</em>';
        const amount = parseFloat(document.getElementById('amount').value);
        const start = document.getElementById('start').value;
        const res = await fetch('/api/best-days', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, start })
        });
        const data = await res.json();
        displayBestDays(data);
        bestSpinner.classList.add('d-none');
        bestBtn.disabled = false;
    });

    resetBtn.addEventListener('click', async () => {
        if(!confirm('Confirmer la r\u00e9initialisation de la base ?')) return;
        resetBtn.disabled = true;
        resetMsg.textContent = '';
        resetSpinner.classList.remove('d-none');
        const res = await fetch('/reset-db', {method:'POST'});
        const data = await res.json();
        if(data.success){
            document.getElementById('date-range').textContent = `Donn\u00e9es disponibles : ${data.min_date} \u00e0 ${data.max_date}`;
            resetMsg.className = 'text-success';
            resetMsg.textContent = 'Base r\u00e9initialis\u00e9e avec succ\u00e8s';
        }else{
            resetMsg.className = 'text-danger';
            resetMsg.textContent = 'Erreur : ' + data.error;
        }
        resetSpinner.classList.add('d-none');
        resetBtn.disabled = false;
    });
});

function exportCsv(purchases){
    let csv = 'date,amount_usd,btc,price_usd\n';
    purchases.forEach(p => {
        csv += `${p.date},${p.amount},${p.btc},${p.price}\n`;
    });
    const blob = new Blob([csv], {type:'text/csv'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'dca_purchases.csv';
    a.click();
    URL.revokeObjectURL(url);
}

let priceChart, fgChart, dcaChart, btcChart, perfChart;
const baseOptions = {
    responsive: true,
    scales: { x: { type: 'time', time: { unit: 'month' } } },
    plugins: { zoom: { zoom: { wheel: {enabled: true}, pinch:{enabled:true}, mode:'x' }, pan: {enabled:true, mode:'x'} } }
};

function drawCharts(dataset){
    const ctx1 = document.getElementById('priceChart').getContext('2d');
    if(priceChart) priceChart.destroy();
    priceChart = new Chart(ctx1, {
        type: 'line',
        data: { labels: dataset.dates, datasets: [{ label: 'Prix BTC (USD)', data: dataset.prices, borderColor: 'blue', fill:false }] },
        options: baseOptions
    });

    const ctx2 = document.getElementById('fgChart').getContext('2d');
    if(fgChart) fgChart.destroy();
    fgChart = new Chart(ctx2, {
        type: 'line',
        data: { labels: dataset.dates, datasets: [{ label: 'Fear & Greed', data: dataset.fg, borderColor:'orange', fill:false }] },
        options: baseOptions
    });
}

function drawDcaChart(progress){
    const ctx = document.getElementById('dcaChart').getContext('2d');
    if(dcaChart) dcaChart.destroy();
    const line = progress.map(p => ({x:p.date, y:p.value}));
    const markers = progress.filter(p=>p.buy).map(p=>({x:p.date, y:p.value}));
    dcaChart = new Chart(ctx, {
        type:'line',
        data:{ datasets:[{ label:'Valeur DCA (USD)', data: line, borderColor:'green', fill:false }, { type:'scatter', label:'Achats', data: markers, pointBackgroundColor:'red', showLine:false }] },
        options: baseOptions
    });
}

function drawBtcChart(progress){
    const ctx = document.getElementById('btcChart').getContext('2d');
    if(btcChart) btcChart.destroy();
    btcChart = new Chart(ctx, {
        type:'line',
        data:{ datasets:[{ label:'BTC accumul\u00e9', data: progress.map(p=>({x:p.date,y:p.btc})), borderColor:'purple', fill:false }] },
        options: baseOptions
    });
}

function drawPerfChart(progress){
    const ctx = document.getElementById('perfChart').getContext('2d');
    if(perfChart) perfChart.destroy();
    perfChart = new Chart(ctx, {
        type:'line',
        data:{ datasets:[{ label:'Performance relative', data: progress.map(p=>({x:p.date,y:p.perf_rel})), borderColor:'teal', fill:false }] },
        options: baseOptions
    });
}

function displayResults(data){
    const div = document.getElementById('results');
    div.innerHTML = `
        <ul class="list-group">
            <li class="list-group-item">Nombre d'achats : ${data.num_purchases}</li>
            <li class="list-group-item">Investissement total : ${data.total_invested.toFixed(2)} USD</li>
            <li class="list-group-item">Bitcoin accumulé : ${data.total_btc.toFixed(8)} BTC</li>
            <li class="list-group-item">Valeur finale : ${data.final_value.toFixed(2)} USD</li>
            <li class="list-group-item">Valeur en achat unique : ${data.lump_value.toFixed(2)} USD</li>
            <li class="list-group-item">Performance : ${data.performance_pct.toFixed(2)}%</li>
        </ul>
    `;
}

function displayBestDays(results){
    results.sort((a,b)=>b.performance_pct - a.performance_pct);
    let html = '<table class="table table-striped table-responsive">';
    html += '<thead><tr><th>Fréquence</th><th>Jour</th><th>Nombre d\'achats</th><th>Total investi</th><th>Valeur finale</th><th>Performance %</th></tr></thead><tbody>';
    results.forEach(r => {
        html += `<tr><td>${r.frequency}</td><td>${r.day}</td><td>${r.num_purchases}</td><td>${r.total_invested.toFixed(2)} USD</td><td>${r.final_value.toFixed(2)} USD</td><td>${r.performance_pct.toFixed(2)}%</td></tr>`;
    });
    html += '</tbody></table>';
    document.getElementById('best-days').innerHTML = html;
}
