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
    const geneticSpinner = document.getElementById('genetic-spinner');
    const optDiv = document.getElementById('opt-smart-result');
    const optStatus = document.getElementById('optimization-status');

    const trendScore = document.getElementById('trend-score');
    const trendsSpinner = document.getElementById('trends-spinner');
    const trendBtns = document.querySelectorAll('.trend-filter');
    const trendCtx = document.getElementById('trendsChart').getContext('2d');
    let trendsChart;

    function arrowHtml(delta){
        const up = delta >= 0;
        const arrow = up ? '▲' : '▼';
        const color = up ? 'green' : 'red';
        const size = 14 + Math.min(Math.abs(delta), 20) / 2;
        return `<span class="arrow" style="color:${color};font-size:${size}px">${arrow}</span>`;
    }

    function loadTrends(period){
        trendsSpinner.classList.remove('d-none');
        trendBtns.forEach(b => b.disabled = true);
        fetch(`/trends?period=${period}`)
            .then(async r => {
                let data;
                try {
                    data = await r.json();
                } catch (e) {
                    throw new Error('Réponse invalide du serveur');
                }
                if(!r.ok){
                    throw new Error(data.error || 'Erreur');
                }
                return data;
            })
            .then(data => {
                const labels = data.scores.map(s=>s.date);
                const vals = data.scores.map(s=>s.score);
                if(trendsChart) trendsChart.destroy();
                trendsChart = new Chart(trendCtx, {
                    type:'line',
                    data:{ labels, datasets:[{ data: vals, borderColor:'#555', pointRadius:0 }] },
                    options:{ responsive:true, maintainAspectRatio:false, scales:{x:{type:'time', time:{unit:'month'}}}, plugins:{legend:{display:false}} }
                });
                trendScore.innerHTML = `${data.current_score} ${arrowHtml(data.delta_percent)}`;
            })
            .catch(err => {
                trendScore.innerHTML = `<span class="text-danger">Erreur : ${err.message}</span>`;
            })
            .finally(() => {
                trendsSpinner.classList.add('d-none');
                trendBtns.forEach(b => b.disabled = false);
            });
    }

    document.querySelectorAll('.trend-filter').forEach(btn=>{
        btn.addEventListener('click', () => {
            document.querySelectorAll('.trend-filter').forEach(b=>b.classList.remove('active'));
            btn.classList.add('active');
            loadTrends(btn.dataset.period);
        });
    });
    loadTrends('month');

    const fgHighInput = document.getElementById('fg_threshold_high');
    const fgLowInput = document.getElementById('fg_threshold_low');
    const bagPctInput = document.getElementById('bag_bonus_pct');
    const bagMaxInput = document.getElementById('bag_bonus_max');
    
    // ========== OPTIMISATION DCA INTELLIGENTE ==========
    const optSmartBtn = document.getElementById('opt-smart-dca-btn');
    const optSmartResult = document.getElementById('opt-smart-result');
    const optSmartSpinner = document.getElementById('opt-smart-spinner');
    const optSmartStatus = document.getElementById('optimization-status');

    function resetOptimizationDisplay() {
        optSmartResult.innerHTML = '';
        optSmartStatus.innerHTML = '';
        optSmartSpinner.classList.remove('d-none');
        optSmartBtn.disabled = true;
    }

    optSmartBtn.addEventListener('click', function() {
        resetOptimizationDisplay();
        optSmartStatus.innerText = 'Optimisation en cours…';

        const amount = document.getElementById('amount').value || 100;
        const start = document.getElementById('start').value || '2018-01-01';
        const frequency = document.getElementById('frequency').value || 'monthly';

        fetch('/api/optimize-smart-dca', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ amount, start, frequency })
        })
        .then(res => res.json())
        .then(data => {
            optSmartSpinner.classList.add('d-none');
            optSmartBtn.disabled = false;

            let phase1perf = data.phase1_performance !== undefined
                ? `${data.phase1_tests || 7000} tests → perf max ${data.phase1_performance.toFixed(2)} %`
                : '';
            let phase2perf = data.best
                ? `${data.phase2_tests || '-'} tests → perf finale ${data.best.performance_pct.toFixed(2)} %`
                : '';

            optSmartStatus.innerHTML = `
                <span>✅ Optimisation terminée</span><br>
                <span>Phase 1 : ${phase1perf}</span><br>
                <span>Phase 2 : ${phase2perf}</span>
            `;

            // Tableau des meilleurs paramètres
            if (data.best) {
                const best = data.best;
                optSmartResult.innerHTML = `
                <table class="table table-bordered table-sm mt-2">
                    <thead><tr>
                      <th>Paramètre</th><th>Valeur</th>
                    </tr></thead>
                    <tbody>
                      <tr><td>Seuil haut FGI</td><td>${best.fg_threshold_high}</td></tr>
                      <tr><td>Seuil bas FGI</td><td>${best.fg_threshold_low}</td></tr>
                      <tr><td>% du bag utilisé</td><td>${best.bag_bonus_pct}</td></tr>
                      <tr><td>Plafond bonus (USD)</td><td>${best.bag_bonus_max}</td></tr>
                      <tr><td>Performance finale</td><td>${best.performance_pct.toFixed(2)} %</td></tr>
                    </tbody>
                </table>
                <button id="apply-best-params" class="btn btn-outline-success mb-3">📥 Appliquer ces paramètres</button>
                `;

                // Pré-remplir automatiquement les champs avancés
                document.getElementById('fg_threshold_high').value = best.fg_threshold_high;
                document.getElementById('fg_threshold_low').value  = best.fg_threshold_low;
                document.getElementById('bag_bonus_pct').value     = best.bag_bonus_pct;
                document.getElementById('bag_bonus_max').value     = best.bag_bonus_max;

                // Réaction au clic sur le bouton "Appliquer ces paramètres"
                document.getElementById('apply-best-params').onclick = () => {
                    document.getElementById('fg_threshold_high').value = best.fg_threshold_high;
                    document.getElementById('fg_threshold_low').value  = best.fg_threshold_low;
                    document.getElementById('bag_bonus_pct').value     = best.bag_bonus_pct;
                    document.getElementById('bag_bonus_max').value     = best.bag_bonus_max;
                };
            } else {
                optSmartResult.innerHTML = `<div class="alert alert-danger">Erreur : aucune configuration optimale trouvée.</div>`;
            }
        })
        .catch(error => {
            optSmartSpinner.classList.add('d-none');
            optSmartBtn.disabled = false;
            optSmartStatus.innerHTML = '<span style="color: red;">Erreur lors de l’optimisation</span>';
            optSmartResult.innerHTML = `<pre>${error}</pre>`;
        });
    });
    // ========== FIN OPTIMISATION DCA INTELLIGENTE ==========
    
    // == ALGO GENETIQUE ==
    const geneticBtn = document.getElementById('genetic-opt-btn');
    const geneticStatus = document.getElementById('genetic-opt-status');
    const geneticResult = document.getElementById('genetic-opt-result');

    if (geneticBtn) {
        geneticBtn.addEventListener('click', function() {
            geneticBtn.disabled = true;
            geneticSpinner.classList.remove('d-none');
            geneticStatus.innerText = "Optimisation génétique en cours…";
            geneticResult.innerHTML = "";

            const amount = document.getElementById('amount')?.value || 100;
            const start = document.getElementById('start')?.value || '2018-01-01';
            const frequency = document.getElementById('frequency')?.value || 'monthly';

            fetch('/api/genetic-optimize-smart-dca', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount, start, frequency })
            })
            .then(res => res.json())
            .then(data => {
                geneticSpinner.classList.add('d-none');
                geneticStatus.innerHTML = "✅ Optimisation génétique terminée";
                if (data.best) {
                    const best = data.best;
                    geneticResult.innerHTML = `
                    <table class="table table-bordered table-sm mt-2">
                        <thead><tr>
                          <th>Paramètre</th><th>Valeur</th>
                        </tr></thead>
                        <tbody>
                          <tr><td>Seuil haut FGI</td><td>${best.fg_threshold_high}</td></tr>
                          <tr><td>Seuil bas FGI</td><td>${best.fg_threshold_low}</td></tr>
                          <tr><td>% du bag utilisé</td><td>${best.bag_bonus_pct}</td></tr>
                          <tr><td>Plafond bonus (USD)</td><td>${best.bag_bonus_max}</td></tr>
                          <tr><td>Performance finale</td><td>${best.performance_pct?.toFixed(2)} %</td></tr>
                        </tbody>
                    </table>
                    <button id="apply-gen-best-params" class="btn btn-outline-success mb-3">📥 Appliquer ces paramètres</button>
                    `;
                    // Remplissage automatique
                    document.getElementById('fg_threshold_high').value = best.fg_threshold_high;
                    document.getElementById('fg_threshold_low').value  = best.fg_threshold_low;
                    document.getElementById('bag_bonus_pct').value     = best.bag_bonus_pct;
                    document.getElementById('bag_bonus_max').value     = best.bag_bonus_max;
                    // Double sécurité (bouton d’application)
                    document.getElementById('apply-gen-best-params').onclick = () => {
                        document.getElementById('fg_threshold_high').value = best.fg_threshold_high;
                        document.getElementById('fg_threshold_low').value  = best.fg_threshold_low;
                        document.getElementById('bag_bonus_pct').value     = best.bag_bonus_pct;
                        document.getElementById('bag_bonus_max').value     = best.bag_bonus_max;
                    };
                } else {
                    geneticResult.innerHTML = `<div class="alert alert-danger">Erreur : aucune configuration optimale trouvée.</div>`;
                }
                geneticBtn.disabled = false;
            })
            .catch(error => {
                geneticSpinner.classList.add('d-none');
                geneticStatus.innerHTML = '<span style="color: red;">Erreur lors de l’optimisation génétique</span>';
                geneticResult.innerHTML = `<pre>${error}</pre>`;
                geneticBtn.disabled = false;
            });
        });
    }
    // == FIN ALGO GENETIQUE ==



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

    let phase1Best = null;
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
        es.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if(data.phase === 'primary_start'){
                if(optStatus) optStatus.textContent = `Test 0 / ${data.total}`;
            }else if(data.phase === 'primary_progress'){
                if(optStatus) optStatus.textContent = `Test ${data.count} / ${data.total}`;
            }else if(data.phase === 'primary_end'){
                phase1Best = data.best;
                if(optStatus) optStatus.innerHTML = `Raffinement autour du minimum trouvé...<br>Test 0 / ${data.total_refine} \u2013 meilleure perf : ${data.best.performance_pct.toFixed(2)} %`;
            }else if(data.phase === 'refine_progress'){
                if(optStatus) optStatus.innerHTML = `Raffinement autour du minimum trouvé...<br>Test ${data.count} / ${data.total} \u2013 meilleure perf : ${data.best_perf.toFixed(2)} %`;
            }else if(data.phase === 'finish'){
                es.close();
                if(optStatus) optStatus.textContent = '✅ Optimisation terminée';
                displayOptimization(data, phase1Best);
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

function displayOptimization(data, phase1Best){
    if(!data.best) return;
    const best = data.best;

    optDiv.innerHTML = '';
    let html = '<div class="table-responsive"><table class="table table-striped">';
    html += '<thead><tr><th>Paramètre</th><th>Valeur</th></tr></thead><tbody>';
    html += `<tr><td>Seuil haut FGI</td><td>${best.fg_threshold_high}</td></tr>`;
    html += `<tr><td>Seuil bas FGI</td><td>${best.fg_threshold_low}</td></tr>`;
    html += `<tr><td>% du bag utilisé</td><td>${best.bag_bonus_pct}</td></tr>`;
    html += `<tr><td>Plafond bonus USD</td><td>${best.bag_bonus_max}</td></tr>`;
    html += `<tr><td>Performance finale</td><td>${best.performance_pct.toFixed(2)} %</td></tr>`;
    html += '</tbody></table></div>';

    if(phase1Best){
        html += `<p>Performance phase 1 : ${phase1Best.performance_pct.toFixed(2)} %</p>`;
    }
    html += `<p>Performance finale après raffinement : ${best.performance_pct.toFixed(2)} %</p>`;

    optDiv.innerHTML = html;

    document.getElementById('fg_threshold_high').value = best.fg_threshold_high;
    document.getElementById('fg_threshold_low').value  = best.fg_threshold_low;
    document.getElementById('bag_bonus_pct').value     = best.bag_bonus_pct;
    document.getElementById('bag_bonus_max').value     = best.bag_bonus_max;
}
