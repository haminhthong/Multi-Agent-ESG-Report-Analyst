/** Bộ điều khiển giao diện Multi-Agent ESG Report Analyst. */

// Các phần tử giao diện dùng xuyên suốt trang.
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
const greenwashingRiskBadge = document.querySelector('#greenwashing-risk-badge');
const greenwashingSignalsList = document.querySelector('#greenwashing-signals-list');

const citationsGridContainer = document.querySelector('#citations-grid-container');
const citationsCountText = document.querySelector('#citations-count-text');

const traceLogsList = document.querySelector('#trace-logs-list');
const limitationsList = document.querySelector('#limitations-list');
const agentStepIds = ['step-doc', 'step-retrieval', 'step-validator', 'step-esg', 'step-explanation'];

// Khởi tạo dữ liệu và sự kiện khi trang sẵn sàng.
document.addEventListener('DOMContentLoaded', () => {
    refreshDashboard();
    setupPresetChips();
    setupDropArea();
});

function refreshDashboard() {
    return Promise.all([loadCorpusStats(), loadDocumentList()]);
}

// Nạp thống kê nhanh của kho dữ liệu.
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

// Nạp danh sách báo cáo đã lập chỉ mục.
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

// Gắn câu hỏi mẫu vào ô nhập liệu.
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

// Thiết lập vùng kéo thả tệp PDF.
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

// Gửi tệp PDF lên API ingestion.
uploadForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    uploadBtn.disabled = true;
    uploadBtn.innerHTML = '<div class="spinner"></div> Đang trích xuất & lập chỉ mục...';

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
        uploadBtn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg> Trích xuất & Index PDF';
    }
});

// Chạy pipeline phân tích nhiều agent.
analyzeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const question = questionInput.value.trim();
    const topK = parseInt(topKInput.value) || 6;
    const modeRadio = document.querySelector('input[name="analysis_mode"]:checked');
    const mode = modeRadio ? modeRadio.value : 'qa';

    if (!question) return;

    // Hiển thị trạng thái chờ và tiến trình agent.
    analyzeBtn.disabled = true;
    agentTraceBox.classList.remove('hidden');
    resultsDisplayArea.classList.add('hidden');
    resetAgentStepper();

    // Mô phỏng tiến trình trong lúc chờ phản hồi API.
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
        renderAnalysisResults(data);

        // Ẩn trạng thái chờ và hiển thị kết quả.
        setTimeout(() => {
            agentTraceBox.classList.add('hidden');
            resultsDisplayArea.classList.remove('hidden');
        }, 500);

    } catch (err) {
        clearInterval(stepInterval);
        alert(`Lỗi kết nối: ${err.message}`);
        agentTraceBox.classList.add('hidden');
    } finally {
        analyzeBtn.disabled = false;
    }
});

// Điều khiển hoạt ảnh tiến trình agent.
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
    }, 400);
}

function completeAgentStepper() {
    agentStepIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.classList.add('active');
    });
}

// Hiển thị kết quả phân tích từ API.
function renderAnalysisResults(data) {
    // 1. Kết luận tổng quan.
    analysisAnswerText.textContent = data.answer || 'Không nhận được câu trả lời.';

    // 2. Coverage overall badge.
    const coverageBadge = document.querySelector('#coverage-badge');
    if (coverageBadge) {
        const cov = data.disclosure_coverage !== undefined ? data.disclosure_coverage : 0;
        coverageBadge.textContent = `OVERALL COVERAGE: ${cov}%`;
        coverageBadge.className = cov >= 50 ? 'risk-badge risk-low' : 'risk-badge risk-high';
    }

    // 3. Danh sách tín hiệu screening.
    const signals = data.screening_signals || [];
    if (signals.length > 0) {
        greenwashingSignalsList.innerHTML = signals.map(sig => `<li>${escapeHtml(sig)}</li>`).join('');
    } else {
        greenwashingSignalsList.innerHTML = '<li>Không phát hiện tín hiệu cần lưu ý. Dữ liệu công bố minh bạch.</li>';
    }

    // 4. Thẻ điểm ba trụ cột E, S, G.
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

    // 5. Danh sách trích dẫn nguồn.
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
                <div class="cite-excerpt">"${escapeHtml(c.excerpt)}"</div>
            </div>
        `).join('');
    }

    // 6. Vết thực thi và giới hạn hệ thống.
    traceLogsList.innerHTML = (data.trace || []).map(t => `<li>${escapeHtml(t)}</li>`).join('');
    limitationsList.innerHTML = (data.limitations || []).map(l => `<li>${escapeHtml(l)}</li>`).join('');
}


// Mã hóa HTML để ngăn chèn mã độc vào giao diện.
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
