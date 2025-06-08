let smartDiv;

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
    const smartBtn = document.getElementById('smart-dca-btn');
    const smartSpinner = document.getElementById('smart-spinner');
    smartDiv = document.getElementById('smart-dca-result');
    const optBtn = document.getElementById('opt-smart-dca-btn');
    const optSpinner = document.getElementById('opt-smart-spinner');
    const optDiv = document.getElementById('opt-smart-result');
    const optStatus = document.getElementById('optimization-status');

    const fgHighInput = document.getElementById('fg_threshold_high');
    const fgLowInput = document.getElementById('fg_threshold_low');
    const bagPctInput = document.getElementById('bag_bonus_pct');
    const bagMaxInput = document.getElementById('bag_bonus_max');

    // Default values
    document.getElementById('amount').value = 100;
    document.getElementById('start').value = '2018-01-01';
    document.getElementById('frequency').value = 'monthly';

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

    smartBtn.addEventListener('click', async () => {
        smartBtn.disabled = true;
        smartSpinner.classList.remove('d-none');
        smartDiv.innerHTML = '<em>Calcul en cours...</em>';
        const amount = parseFloat(document.getElementById('amount').value);
        const start = document.getElementById('start').value;
        const freq = document.getElementById('frequency').value;
        const body = {
            amount,
            start,
            frequency: freq,
            fg_threshold_high: parseFloat(fgHighInput.value),
            fg_threshold_low: parseFloat(fgLowInput.value),
            bag_bonus_pct: parseFloat(bagPctInput.value),
            bag_bonus_max: parseFloat(bagMaxInput.value)
        };
        const res = await fetch('/api/smart-dca', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await res.json();
        if(!res.ok){
            smartDiv.innerHTML = '<span class="text-danger">Erreur : ' + (data.error || 'inconnue') + '</span>';
        }else{
            displaySmartDca(data);
        }
        smartSpinner.classList.add('d-none');
        smartBtn.disabled = false;
    });

    optBtn.addEventListener('click', () => {
        optBtn.disabled = true;
        optSpinner.classList.remove('d-none');
        optDiv.innerHTML = '<em>Optimisation en cours...</em>';
        if(optStatus) optStatus.textContent = 'Optimisation en cours...';

        const amount = parseFloat(document.getElementById('amount').value);
        const start = document.getElementById('start').value;
        const freq = document.getElementById('frequency').value;
        const url = `/api/optimize-smart-dca-stream?amount=${amount}&start=${start}&frequency=${freq}`;
        const es = new EventSource(url);
        let phase1Info = '';
        es.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if(data.phase === 'primary_start'){
                if(optStatus) optStatus.textContent = `Test 0 / ${data.total}`;
            }else if(data.phase === 'primary_progress'){
                if(optStatus) optStatus.textContent = `Test ${data.count} / ${data.total}`;
            }else if(data.phase === 'primary_end'){
                phase1Info = `Phase 1 terminée : ${data.count_primary} tests, meilleure performance : ${data.best.performance_pct.toFixed(2)} %`;
                if(optStatus) optStatus.innerHTML = `${phase1Info}<br>Raffinement autour du minimum trouvé...<br>Test 0 / ${data.total_refine} \u2013 meilleure perf : ${data.best.performance_pct.toFixed(2)} %`;
            }else if(data.phase === 'refine_progress'){
                if(optStatus) optStatus.innerHTML = `${phase1Info}<br>Raffinement autour du minimum trouvé...<br>Test ${data.count} / ${data.total} \u2013 meilleure perf : ${data.best_perf.toFixed(2)} %`;
            }else if(data.phase === 'finish'){
                es.close();
                if(optStatus) optStatus.innerHTML = `${phase1Info}<br>\u2705 Optimisation terminée`;
                displayOptimization(data);
                optSpinner.classList.add('d-none');
                optBtn.disabled = false;
            }
        };
        es.onerror = () => {
            es.close();
            optSpinner.classList.add('d-none');
            optBtn.disabled = false;
            if(optStatus) optStatus.textContent = 'Erreur lors de l\'optimisation';
        };
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
    let html = '<div class="table-responsive"><table class="table table-striped">';
    html += '<thead><tr><th>Fréquence</th><th>Jour</th><th>Nombre d\'achats</th><th>Total investi</th><th>Valeur finale</th><th>Performance %</th></tr></thead><tbody>';
    results.forEach(r => {
        html += `<tr><td>${r.frequency}</td><td>${r.day}</td><td>${r.num_purchases}</td><td>${r.total_invested.toFixed(2)} USD</td><td>${r.final_value.toFixed(2)} USD</td><td>${r.performance_pct.toFixed(2)}%</td></tr>`;
    });
    html += '</tbody></table></div>';
    document.getElementById('best-days').innerHTML = html;
}

function displaySmartDca(data){
    let html = '<div class="table-responsive"><table class="table table-striped">';
    html += '<thead><tr><th>Fréquence</th><th>Total investi</th><th>BTC accumulé</th><th>Valeur finale</th><th>Bag utilisé</th><th>Bag restant</th><th>Performance %</th></tr></thead><tbody>';
    html += `<tr><td>${data.frequency}</td><td>${data.total_invested.toFixed(2)} USD</td><td>${data.btc_total.toFixed(8)} BTC</td><td>${data.final_value.toFixed(2)} USD</td><td>${data.bag_used.toFixed(2)} USD</td><td>${data.bag_remaining.toFixed(2)} USD</td><td>${data.performance_pct.toFixed(2)}%</td></tr>`;
    html += '</tbody></table></div>';
    const bagTotal = data.bag_used + data.bag_remaining;
    if(bagTotal > 0){
        const pctBagUsed = (data.bag_used / bagTotal * 100).toFixed(2);
        const pctNotInvested = (data.bag_remaining / (data.total_invested + data.bag_remaining) * 100).toFixed(2);
        html += `<p>${pctBagUsed}% du bag utilisé</p>`;
        html += `<p>${pctNotInvested}% du capital non investi</p>`;
        if(data.bag_remaining / bagTotal > 0.5){
            html += '<p class="text-warning">⚠️ Plus de 50% du bag n\'a jamais été utilisé</p>';
        }
    }
    html += '<div class="table-responsive mt-3"><table class="table table-striped">';
    html += '<thead><tr><th>Date</th><th>FGI</th><th>Action</th><th>Montant investi</th><th>Bonus utilisé</th><th>Total investi</th><th>Bag après action</th><th>BTC acheté</th></tr></thead><tbody>';
    data.history.forEach(h => {
        html += `<tr><td>${h.date}</td><td>${h.fgi}</td><td>${h.action}</td><td>${h.amount.toFixed(2)}</td><td>${h.bonus.toFixed(2)}</td><td>${h.total.toFixed(2)}</td><td>${h.bag.toFixed(2)}</td><td>${h.btc.toFixed(8)}</td></tr>`;
    });
    html += '</tbody></table></div>';
    smartDiv.innerHTML = html;
}

function displayOptimization(data){
    if(!data.best) return;
    const total = (data.tested_phase1 || 0) + (data.tested_phase2 || 0);
    let html = '<div class="table-responsive"><table class="table table-striped">';
    html += '<thead><tr><th>Paramètre</th><th>Valeur trouvée</th></tr></thead><tbody>';
    html += `<tr><td>Seuil haut FGI</td><td>${data.best.fg_threshold_high}</td></tr>`;
    html += `<tr><td>Seuil bas FGI</td><td>${data.best.fg_threshold_low}</td></tr>`;
    html += `<tr><td>% du bag utilisé</td><td>${data.best.bag_bonus_pct}</td></tr>`;
    html += `<tr><td>Plafond du bonus (USD)</td><td>${data.best.bag_bonus_max}</td></tr>`;
    html += `<tr><td>Performance finale</td><td>${data.best.performance_pct.toFixed(2)} %</td></tr>`;
    html += '</tbody></table></div>';
    html += `<p>Performance phase 1 : ${data.best_initial_perf.toFixed(2)} %</p>`;
    html += `<p>Total des tests : ${total}</p>`;
    html += '<button id="apply-opt-btn" class="btn btn-secondary">\ud83d\udce5 Appliquer ces paramètres</button>';
    optDiv.innerHTML = html;
    const btn = document.getElementById('apply-opt-btn');
    if(btn){
        btn.addEventListener('click', (ev) => {
            ev.preventDefault();
            fgHighInput.value = data.best.fg_threshold_high;
            fgLowInput.value = data.best.fg_threshold_low;
            bagPctInput.value = data.best.bag_bonus_pct;
            bagMaxInput.value = data.best.bag_bonus_max;
        });
    }
}
