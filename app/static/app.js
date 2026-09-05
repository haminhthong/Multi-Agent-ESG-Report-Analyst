/**
 * Evidence-Grounded ESG Intelligence & Audit System
 * Client Controller & Multi-Agent Visualization Dashboard.
 */

// Biến trạng thái toàn cục
let currentEvidenceMatrix = [];
let currentAnalysisResponse = null;

// Các phần tử giao diện dùng xuyên suốt trang
const statDocs = document.querySelector('#stat-docs');
const statChunks = document.querySelector('#stat-chunks');
const statCompanies = document.querySelector('#stat-companies');

const uploadForm = document.querySelector('#upload-form');
const fileInput = document.querySelector('#file-input');
const dropArea = document.querySelector('#drop-area');
const uploadPrompt = dropArea.querySelector('.upload-prompt');
const uploadBtn = document.querySelector('#upload-btn');
const docListContainer = document.querySelector('#document-list-container');
const refreshDocsBtn = document.querySelector('#refresh-docs-btn');

const analyzeForm = document.querySelector('#analyze-form');
const questionInput = document.querySelector('#question-input');
const topKInput = document.querySelector('#top-k-input');
const analyzeBtn = document.querySelector('#analyze-btn');

const agentTraceBox = document.querySelector('#agent-trace-box');
const resultsDisplayArea = document.querySelector('#results-display-area');

const analysisAnswerText = document.querySelector('#analysis-answer-text');
const coverageBadge = document.querySelector('#coverage-badge');
const confidenceBadge = document.querySelector('#confidence-badge');
const engineBadge = document.querySelector('#engine-badge');

const citationsGridContainer = document.querySelector('#citations-grid-container');
const citationsCountText = document.querySelector('#citations-count-text');

const traceLogsList = document.querySelector('#trace-logs-list');
const limitationsList = document.querySelector('#limitations-list');

// 7 bước stepper
const agentStepIds = [
    'step-doc', 'step-plan', 'step-retrieval',
    'step-verify', 'step-extract', 'step-audit', 'step-synth'
];

// Khởi tạo khi DOM sẵn sàng
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    setupPresetChips();
    setupDropArea();
    setupMatrixFilters();
    setupAnalyticsForms();
    refreshDashboard();
});

// Điều khiển chuyển Tab
function setupTabNavigation() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTabId = btn.getAttribute('data-tab');
            tabButtons.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetContent = document.getElementById(targetTabId);
            if (targetContent) targetContent.classList.add('active');
        });
    });
}

function refreshDashboard() {
    return Promise.all([loadCorpusStats(), loadDocumentList()]);
}

// Nạp thống kê nhanh của kho dữ liệu
async function loadCorpusStats() {
    try {
        const response = await fetch('/api/corpus/stats');
        if (!response.ok) return;
        const data = await response.json();
        
        statDocs.textContent = data.documents || 0;
        statChunks.textContent = data.chunks || 0;
        statCompanies.textContent = data.companies || 0;
    } catch (err) {
        console.error('Lỗi nạp thống kê corpus:', err);
    }
}

// Nạp danh sách báo cáo đã lập chỉ mục
async function loadDocumentList() {
    try {
        docListContainer.innerHTML = '<div class="doc-skeleton">Đang nạp danh sách báo cáo...</div>';
        const response = await fetch('/api/documents');
        if (!response.ok) return;
        const docs = await response.json();

        if (docs.length === 0) {
            docListContainer.innerHTML = '<p class="upload-note">Chưa có báo cáo nào. Hãy tải lên tệp PDF đầu tiên.</p>';
            return;
        }

        docListContainer.innerHTML = docs.map(doc => `
            <div class="doc-item-card">
                <div class="doc-name">${escapeHtml(doc.name)}</div>
                <div class="doc-meta">
                    <span class="doc-badge">${escapeHtml(doc.company || 'Doanh nghiệp')}</span>
                    <span>${doc.year || '----'}</span>
                    <span>${doc.page_count || 0} trang (${Math.round((doc.extraction_quality || 0) * 100)}% text)</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        docListContainer.innerHTML = '<p class="upload-note">Không thể kết nối máy chủ.</p>';
    }
}

refreshDocsBtn.addEventListener('click', () => {
    refreshDashboard();
});

// Gắn câu hỏi mẫu vào ô nhập liệu
function setupPresetChips() {
    document.querySelectorAll('.preset-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            const query = btn.getAttribute('data-query');
            if (query) {
                questionInput.value = query;
                questionInput.focus();
            }
        });
    });
}

// Thiết lập vùng kéo thả tệp PDF
function setupDropArea() {
    dropArea.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropArea.classList.add('drop-area-active');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropArea.classList.remove('drop-area-active');
        }, false);
    });

    dropArea.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            fileInput.files = files;
            updateDropAreaLabel(files[0].name);
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            updateDropAreaLabel(fileInput.files[0].name);
        }
    });
}

function updateDropAreaLabel(filename) {
    if (uploadPrompt) {
        uploadPrompt.innerHTML = `Đã chọn tệp: <strong>${escapeHtml(filename)}</strong>`;
    }
}

// Gửi tệp PDF lên API Ingestion
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<div class="spinner"></div> Đang phân loại trang & lập chỉ mục...';

    const formData = new FormData(uploadForm);

    try {
        const response = await fetch('/api/documents', {
            method: 'POST',
            body: formData
        });

        if (response.ok) {
            const result = await response.json();
            alert(`Thành công: Báo cáo ${result.name} đã được lập chỉ mục (${result.pages} trang).`);
            uploadForm.reset();
            if (uploadPrompt) uploadPrompt.innerHTML = 'Kéo thả tệp PDF báo cáo ESG vào đây hoặc <strong>chọn tệp</strong>';
            refreshDashboard();
        } else {
            const errorText = await response.text();
            alert(`Lỗi Ingestion: ${errorText}`);
        }
    } catch (err) {
        alert(`Không thể nạp tệp: ${err.message}`);
    } finally {
        uploadBtn.disabled = false;
        uploadBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Phân tích & Index PDF';
    }
});

// Chạy pipeline phân tích 7 agents
analyzeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    const topK = parseInt(topKInput.value) || 6;
    const modeRadio = document.querySelector('input[name="analysis_mode"]:checked');
    const mode = modeRadio ? modeRadio.value : 'qa';

    if (!question) return;

    // Hiển thị tiến trình
    analyzeBtn.disabled = true;
    agentTraceBox.classList.remove('hidden');
    resultsDisplayArea.classList.add('hidden');
    resetAgentStepper();

    const stepInterval = animateAgentSteps();

    try {
        const response = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, top_k: topK, mode: mode })
        });

        clearInterval(stepInterval);
        completeAgentStepper();

        if (!response.ok) {
            const errObj = await response.json().catch(() => ({}));
            const msg = errObj.error ? errObj.error.message : 'Lỗi không xác định';
            alert(`Lỗi phân tích: ${msg}`);
            agentTraceBox.classList.add('hidden');
            return;
        }

        const data = await response.json();
        currentAnalysisResponse = data;
        currentEvidenceMatrix = data.evidence_matrix || [];

        renderAnalysisResults(data);
        renderEvidenceMatrix(currentEvidenceMatrix);
        renderGreenwashingScreening(data.screening_result, data.conflicts);
        renderTraceWaterfall(data.trace_steps, data.trace, data.limitations);

        setTimeout(() => {
            agentTraceBox.classList.add('hidden');
            resultsDisplayArea.classList.remove('hidden');
        }, 400);

    } catch (err) {
        clearInterval(stepInterval);
        alert(`Lỗi kết nối: ${err.message}`);
        agentTraceBox.classList.add('hidden');
    } finally {
        analyzeBtn.disabled = false;
    }
});

// Điều khiển Stepper
function resetAgentStepper() {
    agentStepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.remove('active');
    });
    const docEl = document.getElementById('step-doc');
    if (docEl) docEl.classList.add('active');
}

function animateAgentSteps() {
    let currentStep = 0;
    return setInterval(() => {
        currentStep = (currentStep + 1) % agentStepIds.length;
        agentStepIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.classList.remove('active');
        });
        const activeEl = document.getElementById(agentStepIds[currentStep]);
        if (activeEl) activeEl.classList.add('active');
    }, 350);
}

function completeAgentStepper() {
    agentStepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
    });
}

// 1. Hiển thị kết quả Tab 1 (Q&A & Rubric Scorecards)
function renderAnalysisResults(data) {
    analysisAnswerText.textContent = data.answer || 'Không nhận được câu trả lời.';

    if (coverageBadge) {
        const cov = data.disclosure_coverage !== undefined ? data.disclosure_coverage : 0;
        coverageBadge.textContent = `OVERALL COVERAGE: ${cov}%`;
        coverageBadge.className = cov >= 50 ? 'risk-badge risk-low' : 'risk-badge risk-high';
    }

    if (confidenceBadge) {
        const conf = data.confidence !== undefined ? Math.round(data.confidence * 100) : 0;
        confidenceBadge.textContent = `CONFIDENCE: ${conf}%`;
        confidenceBadge.className = conf >= 60 ? 'risk-badge risk-low' : 'risk-badge risk-medium';
    }

    if (engineBadge) {
        engineBadge.textContent = (data.agent_mode || 'deterministic').toUpperCase();
    }

    // Ba trụ cột E, S, G
    (data.pillars || []).forEach(p => {
        const pillarKey = p.pillar.toUpperCase();
        const scoreVal = document.getElementById(`score-val-${pillarKey}`);
        const discVal = document.getElementById(`disc-val-${pillarKey}`);
        const discBar = document.getElementById(`disc-bar-${pillarKey}`);
        const perfVal = document.getElementById(`perf-val-${pillarKey}`);
        const perfBar = document.getElementById(`perf-bar-${pillarKey}`);
        const qualVal = document.getElementById(`qual-val-${pillarKey}`);
        const qualBar = document.getElementById(`qual-bar-${pillarKey}`);
        const findingsBox = document.getElementById(`findings-${pillarKey}`);

        if (scoreVal) scoreVal.textContent = `${p.disclosure_coverage || 0}%`;
        if (discVal) discVal.textContent = `${p.disclosure_coverage || 0}%`;
        if (discBar) discBar.style.width = `${p.disclosure_coverage || 0}%`;
        if (qualVal) qualVal.textContent = `${p.evidence_quality || 0}%`;
        if (qualBar) qualBar.style.width = `${p.evidence_quality || 0}%`;
        if (perfVal) perfVal.textContent = `${p.data_completeness || 0}%`;
        if (perfBar) perfBar.style.width = `${p.data_completeness || 0}%`;

        if (findingsBox) {
            findingsBox.innerHTML = `
                <p><strong>Bằng chứng:</strong> ${escapeHtml((p.findings || []).join(' '))}</p>
                ${(p.risks || []).length > 0 ? `<p style="color:#fbbf24; margin-top:4px;"><strong>Lưu ý:</strong> ${escapeHtml(p.risks.join(' '))}</p>` : ''}
            `;
        }
    });

    // Danh sách trích dẫn nguồn theo trang
    const citations = data.citations || [];
    citationsCountText.textContent = `${citations.length} verified citations`;

    if (citations.length === 0) {
        citationsGridContainer.innerHTML = '<p class="upload-note">Không tìm thấy đoạn bằng chứng phù hợp trong corpus.</p>';
    } else {
        citationsGridContainer.innerHTML = citations.map(c => `
            <div class="citation-card">
                <div class="citation-meta">
                    <span class="cite-doc-name">${escapeHtml(c.document_name)}</span>
                    <span class="cite-page-tag">TRANG ${c.page}</span>
                </div>
                ${c.section ? `<div style="font-size:11px; color:#34d399; margin-bottom:4px;">📁 ${escapeHtml(c.section)}</div>` : ''}
                <div class="cite-excerpt">"${escapeHtml(c.excerpt)}"</div>
            </div>
        `).join('');
    }
}

// 2. Hiển thị kết quả Tab 2 (Evidence Matrix)
function setupMatrixFilters() {
    const pillarFilter = document.getElementById('matrix-pillar-filter');
    const statusFilter = document.getElementById('matrix-status-filter');

    if (pillarFilter && statusFilter) {
        const applyFilter = () => {
            const pVal = pillarFilter.value;
            const sVal = statusFilter.value;
            const filtered = currentEvidenceMatrix.filter(row => {
                const matchPillar = pVal === 'all' || row.pillar === pVal;
                const matchStatus = sVal === 'all' || row.status === sVal;
                return matchPillar && matchStatus;
            });
            renderEvidenceMatrix(filtered);
        };
        pillarFilter.addEventListener('change', applyFilter);
        statusFilter.addEventListener('change', applyFilter);
    }
}

function renderEvidenceMatrix(rows) {
    const tbody = document.getElementById('audit-matrix-body');
    if (!tbody) return;

    if (!rows || rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center-cell">Không có tiêu chí nào phù hợp với bộ lọc hiện tại.</td></tr>';
        return;
    }

    tbody.innerHTML = rows.map(r => {
        let statusBadge = '<span class="matrix-status-missing">Thiếu</span>';
        if (r.status === 'found') {
            statusBadge = '<span class="matrix-status-found">✓ Đã công bố</span>';
        } else if (r.status === 'contradicts') {
            statusBadge = '<span class="matrix-status-contradicts">❌ Mâu thuẫn</span>';
        }

        const pillarClass = r.pillar === 'E' ? 'pill-e' : (r.pillar === 'S' ? 'pill-s' : 'pill-g');
        const citationRef = r.citation ? `Trang ${r.citation.page} (${escapeHtml(r.citation.document)})` : '---';
        const displayVal = r.value !== null && r.value !== undefined ? escapeHtml(r.value) : '---';
        const displayUnit = r.unit ? escapeHtml(r.unit) : '---';
        const displayYear = r.reporting_year ? r.reporting_year : '---';
        const confText = r.confidence ? `${Math.round(r.confidence * 100)}%` : '0%';

        return `
            <tr>
                <td><span class="matrix-pillar-pill ${pillarClass}">${r.pillar}</span></td>
                <td><strong>${escapeHtml(r.criterion_name)}</strong><br><small style="color:var(--text-dim);">${escapeHtml(r.criterion_id)}</small></td>
                <td>${statusBadge}</td>
                <td><strong>${displayVal}</strong></td>
                <td>${displayUnit}</td>
                <td>${displayYear}</td>
                <td><small>${citationRef}</small></td>
                <td>${confText}</td>
            </tr>
        `;
    }).join('');
}

// 3. Hiển thị kết quả Tab 3 (Greenwashing Screening Radar)
function renderGreenwashingScreening(screening, conflicts) {
    const riskBadge = document.getElementById('gw-overall-risk-badge');
    const targetList = document.getElementById('gw-target-signals');
    const evidenceList = document.getElementById('gw-evidence-signals');
    const narrativeList = document.getElementById('gw-narrative-signals');
    const conflictsList = document.getElementById('conflicts-list');

    if (!screening) return;

    if (riskBadge) {
        riskBadge.textContent = `RISK LEVEL: ${screening.risk_level}`;
        riskBadge.className = screening.risk_level === 'LOW' ? 'risk-badge risk-low' : (
            screening.risk_level === 'MEDIUM' ? 'risk-badge risk-medium' : 'risk-badge risk-high'
        );
    }

    if (targetList) {
        targetList.innerHTML = (screening.target_credibility_signals || []).map(s => {
            const isWarn = s.includes('⚠') || s.includes('thiếu');
            return `<li class="${isWarn ? 'warn' : ''}">${escapeHtml(s)}</li>`;
        }).join('') || '<li>Không ghi nhận tín hiệu cảnh báo.</li>';
    }

    if (evidenceList) {
        evidenceList.innerHTML = (screening.evidence_quality_signals || []).map(s => {
            const isWarn = s.includes('⚠') || s.includes('thiếu') || s.includes('KHÔNG');
            return `<li class="${isWarn ? 'warn' : ''}">${escapeHtml(s)}</li>`;
        }).join('') || '<li>Không ghi nhận tín hiệu cảnh báo.</li>';
    }

    if (narrativeList) {
        narrativeList.innerHTML = (screening.narrative_risk_signals || []).map(s => {
            const isWarn = s.includes('⚠') || s.includes('vượt trội');
            return `<li class="${isWarn ? 'warn' : ''}">${escapeHtml(s)}</li>`;
        }).join('') || '<li>Văn phong cân bằng, không lạm dụng từ ngữ tham vọng suông.</li>';
    }

    if (conflictsList) {
        if (!conflicts || conflicts.length === 0) {
            conflictsList.innerHTML = '<p class="upload-note">✓ Không phát hiện mâu thuẫn số liệu giữa các trang báo cáo.</p>';
        } else {
            conflictsList.innerHTML = conflicts.map(cf => `
                <div class="conflict-item-card">
                    <div style="font-weight:700; color:#ef4444; margin-bottom:4px;">Chỉ số: ${escapeHtml(cf.metric)} (Mức độ: ${cf.severity.toUpperCase()})</div>
                    <p>${escapeHtml(cf.description)}</p>
                    <div style="font-size:11px; color:var(--text-dim); margin-top:4px;">${escapeHtml(cf.resolution_guidance || '')}</div>
                </div>
            `).join('');
        }
    }
}

// 4. Thiết lập & Hiển thị Tab 4 (So sánh & Xu hướng)
function setupAnalyticsForms() {
    const compareForm = document.getElementById('compare-form');
    const compareInput = document.getElementById('compare-companies-input');
    const compareContainer = document.getElementById('compare-results-container');

    if (compareForm) {
        compareForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const val = compareInput.value.trim();
            if (!val) return;
            const companies = val.split(',').map(s => s.trim()).filter(Boolean);
            compareContainer.innerHTML = '<div class="doc-skeleton">Đang truy xuất và đối soát dữ liệu giữa các doanh nghiệp...</div>';

            try {
                const res = await fetch('/api/compare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ companies })
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                renderComparisonResults(data, compareContainer);
            } catch (err) {
                compareContainer.innerHTML = `<p class="upload-note" style="color:#ef4444;">Lỗi đối sánh: ${err.message}</p>`;
            }
        });
    }

    const temporalForm = document.getElementById('temporal-form');
    const temporalCompany = document.getElementById('temporal-company-input');
    const temporalMetric = document.getElementById('temporal-metric-input');
    const temporalContainer = document.getElementById('temporal-results-container');

    if (temporalForm) {
        temporalForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const company = temporalCompany.value.trim();
            const metric = temporalMetric.value;
            if (!company) return;
            temporalContainer.innerHTML = '<div class="doc-skeleton">Đang trích xuất dữ liệu chuỗi thời gian...</div>';

            try {
                const res = await fetch('/api/temporal', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ company, metric })
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                renderTemporalResults(data, temporalContainer);
            } catch (err) {
                temporalContainer.innerHTML = `<p class="upload-note" style="color:#ef4444;">Lỗi phân tích: ${err.message}</p>`;
            }
        });
    }
}

function renderComparisonResults(data, container) {
    const companies = data.companies || [];
    const matrix = data.criteria_matrix || [];

    if (matrix.length === 0) {
        container.innerHTML = '<p class="upload-note">Không tìm thấy đủ dữ liệu để so sánh các doanh nghiệp này.</p>';
        return;
    }

    let headerHtml = '<th>Tiêu chí ESG</th>' + companies.map(c => `<th>${escapeHtml(c)} (Cov: ${data.coverage_summary[c] || 0}%)</th>`).join('');

    let rowsHtml = matrix.map(row => {
        let cells = `<td><strong>${escapeHtml(row.criterion_name)}</strong></td>`;
        companies.forEach(c => {
            const valObj = row.values_by_company[c] || {};
            const isFound = valObj.status === 'found';
            const display = isFound ? `<strong>${valObj.value || 'Đã công bố'}</strong> (Trang ${valObj.page || '?'})` : '<span style="color:#f59e0b;">Chưa công bố</span>';
            cells += `<td>${display}</td>`;
        });
        return `<tr>${cells}</tr>`;
    }).join('');

    container.innerHTML = `
        <table class="audit-matrix-table">
            <thead><tr>${headerHtml}</tr></thead>
            <tbody>${rowsHtml}</tbody>
        </table>
    `;
}

function renderTemporalResults(data, container) {
    const timeline = data.timeline || [];
    if (timeline.length === 0) {
        container.innerHTML = `<p class="upload-note">Chưa tìm thấy số liệu qua các năm cho chỉ số '${escapeHtml(data.metric)}' của ${escapeHtml(data.company)}.</p>`;
        return;
    }

    let summaryText = `Báo cáo nhất quán: <strong>${data.reporting_consistency}</strong>. `;
    if (data.baseline_to_current_change !== null) {
        const sign = data.baseline_to_current_change > 0 ? '+' : '';
        summaryText += `Biến động tổng thể so với năm đầu: <strong>${sign}${data.baseline_to_current_change}%</strong>.`;
    }

    let tableRows = timeline.map(p => `
        <tr>
            <td><strong>Năm ${p.year}</strong></td>
            <td><strong>${p.value}</strong></td>
            <td>${p.unit || '---'}</td>
            <td>Trang ${p.page || '---'}</td>
        </tr>
    `).join('');

    let yoyHtml = (data.yoy_changes || []).map(ch => `
        <li>Từ ${ch.from_year} → ${ch.to_year}: <strong>${ch.change_pct > 0 ? '+' : ''}${ch.change_pct}%</strong></li>
    `).join('');

    container.innerHTML = `
        <p style="margin-bottom:12px; color:#fff;">${summaryText}</p>
        <table class="audit-matrix-table" style="margin-bottom:16px;">
            <thead><tr><th>Năm</th><th>Giá trị</th><th>Đơn vị</th><th>Nguồn</th></tr></thead>
            <tbody>${tableRows}</tbody>
        </table>
        ${yoyHtml ? `<div style="font-size:12px; color:var(--text-muted);"><strong style="color:#fff;">Biến động YoY:</strong><ul style="padding-left:18px; margin-top:6px;">${yoyHtml}</ul></div>` : ''}
    `;
}

// 5. Hiển thị kết quả Tab 5 (Latency Waterfall & Observability)
function renderTraceWaterfall(traceSteps, logs, limitations) {
    const container = document.getElementById('waterfall-container');
    const totalLatencyEl = document.getElementById('total-trace-latency');

    if (!traceSteps || traceSteps.length === 0) {
        if (container) container.innerHTML = '<p class="upload-note">Chưa có vết thực thi để hiển thị.</p>';
        return;
    }

    const totalLat = traceSteps.reduce((acc, step) => acc + (step.latency_ms || 0), 0);
    if (totalLatencyEl) totalLatencyEl.textContent = `${totalLat.toFixed(2)} ms`;

    const maxLat = Math.max(...traceSteps.map(s => s.latency_ms || 0), 1);

    if (container) {
        container.innerHTML = traceSteps.map(s => {
            const pct = Math.min(100, Math.max(8, (s.latency_ms / maxLat) * 100));
            return `
                <div class="waterfall-row">
                    <div class="waterfall-agent-name">${escapeHtml(s.agent)}</div>
                    <div class="waterfall-bar-track">
                        <div class="waterfall-bar-fill" style="width: ${pct}%"></div>
                    </div>
                    <div class="waterfall-latency-text">${s.latency_ms.toFixed(1)} ms</div>
                </div>
            `;
        }).join('');
    }

    if (traceLogsList) {
        traceLogsList.innerHTML = (logs || []).map(t => `<li>${escapeHtml(t)}</li>`).join('');
    }

    if (limitationsList) {
        limitationsList.innerHTML = (limitations || []).map(l => `<li>${escapeHtml(l)}</li>`).join('');
    }
}

// Mã hóa HTML ngăn chèn mã độc
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
