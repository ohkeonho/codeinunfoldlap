// plaint.js - 고소장 목록 페이지 스크립트 (목록 표시 내용 수정 및 텍스트 다운로드 로직 포함)

// === 전역 변수 ===
let isFirebaseInitialized_plaint = false; // 이 페이지의 Firebase 초기화 상태
let currentUserToken_plaint = null;       // 이 페이지에서 사용할 현재 사용자 토큰
let activeDetailRow = null; // 현재 상세 내용이 열려있는 클라이언트 목록 행 (tr)

// === 유틸리티 함수 ===

// 기존 상세 패널 닫기 함수
function closeDetailPanel() {
    console.log("Closing detail panel (called from plaint.js - legacy)...");
    const panel = document.getElementById('detailPanel');
    const backdrop = document.getElementById('modalBackdrop');
    const container = document.querySelector('.admin-container') || document.querySelector('.main-content-area');

    if (panel) panel.classList.remove('active');
    if (backdrop) backdrop.classList.remove('active');
    if (container) container.classList.remove('detail-panel-active');
}

// 목록 아래 삽입된 클라이언트 상세 내용 영역 (TR)을 닫는 함수
function closeActiveDetailRow() {
    if (activeDetailRow) {
        console.log("Closing active client detail area...");
        activeDetailRow.classList.remove('active-detail-row');
        const detailRow = activeDetailRow.nextElementSibling;
        if (detailRow && detailRow.classList.contains('detail-row-inserted')) {
            detailRow.remove();
        }
        activeDetailRow = null;
    }
}

// HTML 이스케이프 함수
const escapeHtml = (unsafe) => {
    if (typeof unsafe !== 'string') return '';
    return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
};

// --- 파일 이름 생성을 위한 sanitize 함수 (백엔드와 유사하게) ---
const sanitizeFilenameForJS = (filename) => {
    if (typeof filename !== 'string') return 'invalid_filename';
    let sanitized = filename.replace(/[\/\\?%*:|"<>]/g, '-');
    sanitized = sanitized.replace(/\s+/g, '_');
    return sanitized.substring(0, 100); // 예: 최대 100자
};


// === 수정된 파일/링크 목록 내용을 HTML로 렌더링 (녹취록/증거파일 - 변경 없음) ===
function renderFileListContent(fileMetadataList, typeSingular) {
    console.log(`[renderFileListContent] Rendering ${typeSingular} list. Count: ${fileMetadataList?.length}.`);
    if (!fileMetadataList || fileMetadataList.length === 0) {
        return `<p class="no-data" style="margin: 10px 0;">등록된 ${typeSingular} 없음.</p>`;
    }
    const listItems = fileMetadataList.map(file => {
        const originalFilename = escapeHtml(file.original_filename || `이름 없는 ${typeSingular}`);
        const storageKey = file.storage_key;
        const processedFilename = file.processed_filename;

        if (storageKey && processedFilename) {
            return `<li style="margin-bottom: 5px;">
                        <a href="#"
                           class="download-link"
                           data-storage-key="${escapeHtml(storageKey)}"
                           data-processed-filename="${escapeHtml(processedFilename)}"
                           data-original-filename="${originalFilename}"
                           style="cursor: pointer; color: #007bff; text-decoration: underline;"
                           title="${originalFilename} 다운로드">
                           ${originalFilename}
                        </a> (Topic: ${escapeHtml(file.key_topic || 'N/A')})
                        </li>`;
        } else {
            console.warn(`[renderFileListContent - ${typeSingular}] Cannot create download link for ${originalFilename}. Missing SK or PFN.`);
            return `<li>${originalFilename} (다운로드 불가 - 정보 부족)</li>`;
        }
    }).join('');
    return `<ul style="list-style: disc; padding: 0 20px; margin: 10px 0; max-height: 150px; overflow-y: auto;">${listItems}</ul>`;
}


// === 통합 문서 목록 (클라이언트 상세 내에서 사용 - 변경 없음) ===
function renderCombinedDocumentListContent(documents) {
    if (!documents || documents.length === 0) {
        return `<p class="no-data" style="margin: 10px 0;">관련 문서가 없습니다.</p>`;
    }
    const documentItemsHtml = documents.map(doc => {
        const name = escapeHtml(doc.name || '제목 없음');
        const topic = escapeHtml(doc.topic || '종류 정보 없음');
        const date = (doc.date_created || doc.timestamp) ? escapeHtml(new Date(doc.date_created || doc.timestamp).toISOString().substring(0, 10)) : '날짜 정보 없음';
        const storageKey = escapeHtml(doc.storage_key || '');

        if (!storageKey) {
             return `
                    <div class="combined-doc-item" style="margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px dashed #ddd;">
                        <div style="color: #888; font-weight: bold;">[${topic}] ${name} (${date}) (키 누락)</div>
                        <div style="color: red; padding: 10px 0;">상세 정보 로드 불가</div>
                    </div>`;
        }
        return `
                <div class="combined-doc-item" style="margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px dashed #ddd;">
                    <div class="combined-doc-header" data-storage-key="${storageKey}" style="cursor: pointer; font-weight: bold; color: #007bff;">
                        [${topic}] ${name} (${date})
                    </div>
                    <div class="combined-doc-detail-content" style="display: none; padding: 10px 0; background-color: #f1f1f1; border-left: 3px solid #007bff;">
                        <div style="text-align: center; padding: 10px;">상세 내용 로딩 중...</div>
                    </div>
                </div>`;
    }).join('');
    return `<div style="margin: 10px 0;">${documentItemsHtml}</div>`;
}


// === 초기 목록에 표시할 서면 요약 목록 HTML 렌더링 (이제 loadComplaints에서 직접 사용되지 않음) ===
function renderInitialDocumentSummaryList(documents) {
    if (!documents || documents.length === 0) {
         return `<small class="no-data">등록된 서면 없음</small>`;
    }
    const listItems = documents.map(doc => {
        const topic = escapeHtml(doc.topic || '문서');
        const name = escapeHtml(doc.name || '제목 없음');
        const dateStr = doc.date || (doc.timestamp ? doc.timestamp.substring(0, 10) : '');
        const date = dateStr ? escapeHtml(dateStr) : '';
        const storageKey = escapeHtml(doc.storage_key || '');

        if (!storageKey) {
            return `<li style="margin-bottom: 4px; color: #888; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="[${topic}] ${name} (상세 정보 없음)">[${topic}] ${name} (${date}) (키 누락)</li>`;
        }
        return `<li data-storage-key="${storageKey}" style="margin-bottom: 4px; cursor: pointer; color: #007bff; text-decoration: underline; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="[${topic}] ${name} 상세 보기">[${topic}] ${name} (${date})</li>`;
    }).join('');
    return `<ul style="list-style: none; padding: 0; margin: 0; max-height: 80px; overflow-y: auto;">${listItems}</ul>`;
}


// === 특정 서면의 상세 내용을 불러와 모달 등에 표시 (텍스트 다운로드 링크로 수정) ===
async function showDocumentDetail(storageKey, title) {
    const modal = document.getElementById('documentDetailModal');
    const contentDiv = document.getElementById('documentDetailContent');
    const titleSpan = document.getElementById('documentDetailTitle');
    const backdrop = document.getElementById('modalBackdrop');
    if (!modal || !contentDiv || !titleSpan || !backdrop) { console.error("Modal elements missing!"); alert("상세 정보 창 오류"); return; }

    titleSpan.textContent = title || '상세 정보';
    contentDiv.innerHTML = '<p style="text-align:center; padding: 20px;">상세 정보 로딩 중...</p>';
    modal.style.display = 'block'; backdrop.classList.add('active');
    if (!currentUserToken_plaint) { contentDiv.innerHTML = '<p style="color:red; text-align:center;">오류: 인증 토큰 없음</p>'; return; }

    const detailApiEndpoint = `/api/memory/${encodeURIComponent(storageKey)}`;
    try {
        const response = await fetch(detailApiEndpoint, { headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` } });
        if (!response.ok) throw new Error(`서버 오류 (${response.status})`);
        const data = await response.json();

        // --- 텍스트 다운로드 링크 생성 ---
        let downloadLinkHtml = '';
        const textDownloadBaseUrl = `/api/memory/download_text/${encodeURIComponent(storageKey)}`;
        const metadata = data.metadata || {};
        const clientName = sanitizeFilenameForJS(metadata.name || 'unknown');
        const keyTopic = sanitizeFilenameForJS(metadata.key_topic || 'doc');
        const timestampStr = (data.timestamp || '').split('T')[0] || 'nodate';

        if (data.summary) {
            const summaryFilename = `${clientName}_${keyTopic}_${timestampStr}_summary.txt`;
            const summaryDownloadUrl = `${textDownloadBaseUrl}?content=summary`;
            downloadLinkHtml += `<a href="#" class="text-download-link" data-download-url="${summaryDownloadUrl}" data-download-filename="${summaryFilename}" style="cursor: pointer; color: #007bff; text-decoration: underline; font-weight: bold; font-size: 0.9em; margin-left: 15px;" title="${summaryFilename} 다운로드"><i class="fas fa-file-alt"></i> [요약 다운로드]</a>`;
        }
        const mainContent = data.files_content || data.original;
        if (mainContent) {
            const isContent = !!data.files_content;
            const mainContentDownloadUrl = `${textDownloadBaseUrl}?content=${isContent ? 'content' : 'original'}`;
            const mainContentFilename = `${clientName}_${keyTopic}_${timestampStr}_${isContent ? 'content' : 'original'}.txt`;
            downloadLinkHtml += `<a href="#" class="text-download-link" data-download-url="${mainContentDownloadUrl}" data-download-filename="${mainContentFilename}" style="cursor: pointer; color: #007bff; text-decoration: underline; font-weight: bold; font-size: 0.9em; margin-left: 15px;" title="${mainContentFilename} 다운로드"><i class="fas fa-file-alt"></i> [원문/내용 다운로드]</a>`;
        }
        if (downloadLinkHtml) { downloadLinkHtml = `<div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee; text-align: right;">${downloadLinkHtml}</div>`; }
        else { downloadLinkHtml = `<div style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #eee; text-align: right; color: grey; font-size: 0.9em;">다운로드 가능한 텍스트 내용 없음</div>`; }

        // --- 내용 표시 ---
        const mainContentText = data.files_content || data.original || '[원문/내용 없음]';
        contentDiv.innerHTML = `
             <h4>요약</h4><p style="white-space: pre-wrap;">${escapeHtml(data.summary || '[요약 없음]')}</p>
             <h4>원문/내용</h4><pre style="white-space: pre-wrap; word-wrap: break-word; background-color: #f8f9fa; padding: 10px; border: 1px solid #dee2e6; max-height: 300px; overflow-y: auto;">${escapeHtml(mainContentText)}</pre>
             ${downloadLinkHtml}
         `;
        console.log("[Plaint Modal Detail] Content loaded.");
    } catch (error) {
        console.error('[Plaint Modal Detail] Error loading detail:', error);
        contentDiv.innerHTML = `<p style="color:red; text-align:center;">상세 정보 로드 오류: ${escapeHtml(error.message)}</p>`;
    }
}


// === 클라이언트 상세 행 내에서 특정 서면 상세 내용 표시 (인라인 아코디언 - 텍스트 다운로드 링크로 수정) ===
async function showInlineDocumentDetail(storageKey, clickedHeaderElement) {
    console.log(`[Plaint Detail - Inline] showOrHide for key: ${storageKey}`);
    const detailContentDiv = clickedHeaderElement.nextElementSibling;
    if (!detailContentDiv || !detailContentDiv.classList.contains('combined-doc-detail-content')) { return; }

    clickedHeaderElement.closest('.detail-area-container')?.querySelectorAll('.combined-doc-detail-content').forEach(content => {
        if (content !== detailContentDiv && content.style.display !== 'none') {
            content.style.display = 'none';
            content.previousElementSibling?.classList.remove('active-inline-header');
        }
    });
    const isCurrentlyVisible = detailContentDiv.style.display !== 'none';
    const shouldShow = !isCurrentlyVisible;
    detailContentDiv.style.display = shouldShow ? 'block' : 'none';
    clickedHeaderElement.classList.toggle('active-inline-header', shouldShow);
    console.log(`[Plaint Detail - Inline] Toggled ${shouldShow ? 'open' : 'closed'} for key: ${storageKey}`);

    const needsLoading = shouldShow && detailContentDiv.innerHTML.includes('로딩 중...');
    if (needsLoading) {
        detailContentDiv.innerHTML = '<div style="text-align: center; padding: 10px;">상세 내용 로딩 중...</div>';
        if (!currentUserToken_plaint) { detailContentDiv.innerHTML = '<div style="color: red;">오류: 인증 토큰 없음</div>'; return; }

        const documentDetailApiEndpoint = `/api/memory/${encodeURIComponent(storageKey)}`;
        try {
            const response = await fetch(documentDetailApiEndpoint, { headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` } });
            if (!response.ok) throw new Error(`서버 오류 (${response.status})`);
            const detailData = await response.json();
            if (!detailData) throw new Error("빈 응답 데이터");

            console.log("[Plaint Detail - Inline] Document detail data received:", detailData);

            // --- ▼▼▼ 텍스트 다운로드 링크 생성 (수정됨) ▼▼▼ ---
            let inlineDownloadLinkHtml = '';
            const textDownloadBaseUrl = `/api/memory/download_text/${encodeURIComponent(storageKey)}`;
            const summaryDownloadUrlInline = `${textDownloadBaseUrl}?content=summary`;

            const metadataInline = detailData.metadata || {};
            const clientNameInline = sanitizeFilenameForJS(metadataInline.name || 'unknown');
            const keyTopicInline = sanitizeFilenameForJS(metadataInline.key_topic || 'doc');
            const timestampStrInline = (detailData.timestamp || '').split('T')[0] || 'nodate';
            const summaryFilenameInline = `${clientNameInline}_${keyTopicInline}_${timestampStrInline}_summary.txt`;

            const summaryText = escapeHtml(detailData.summary || '[요약 정보 없음]');

            
            // --- ▲▲▲ 텍스트 다운로드 링크 생성 끝 ▲▲▲ ---

            detailContentDiv.innerHTML = `
                <div class="inline-summary-only" style="padding: 10px; border: 1px solid #ddd; background-color: #f9f9f9;">
                    <p style="margin: 0; white-space: pre-wrap; word-wrap: break-word;">${summaryText}</p>
                    ${inlineDownloadLinkHtml}
                </div>`;

        } catch (error) {
            console.error('[Plaint Detail - Inline] Error loading document detail:', error);
            detailContentDiv.innerHTML = `<div style="color: red; text-align: center;">상세 내용 로드 오류: ${escapeHtml(error.message)}</div>`;
        }
    }
}

// === 메인 함수: 클라이언트 목록 로드 및 행 이벤트 설정 (내용 표시 수정됨) ===
async function loadComplaints() {
    const memberListBody = document.getElementById('member-list-body');
    const itemTemplate = document.getElementById('summary-row-template');
    const columnCount = 6; // 테이블 컬럼 수

    if (!memberListBody || !itemTemplate || !itemTemplate.content) {
        console.error("CRITICAL: Required elements missing for loadComplaints.");
        if(memberListBody) memberListBody.innerHTML = `<tr><td colspan="${columnCount}">페이지 오류.</td></tr>`;
        return;
    }
    memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center; padding: 20px;">클라이언트 목록 로딩 중...</td></tr>`;

    let idToken;
    try {
        const currentUser = firebase.auth().currentUser;
        if (!isFirebaseInitialized_plaint || !currentUser) throw new Error("로그인이 필요합니다.");
        idToken = await currentUser.getIdToken(false);
        currentUserToken_plaint = idToken;
        console.log(`[Plaint] ID Token acquired.`);
    } catch (error) {
         console.error('[Plaint] Failed to get ID token:', error);
         memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align:center; color:red;">인증 토큰 오류. (${error.message})</td></tr>`;
         return;
    }

    const listApiEndpoint = '/api/clients';
    console.log(`[Plaint] Loading client list from ${listApiEndpoint}...`);

    try {
        const response = await fetch(listApiEndpoint, { headers: { 'Authorization': `Bearer ${idToken}` } });
        if (!response.ok) {
            let errorDetail = `서버 오류 (${response.status})`;
            try {
                const errorData = await response.json();
                errorDetail += `: ${errorData.error || errorData.detail || JSON.stringify(errorData)}`;
            } catch (e) {
                const text = await response.text();
                errorDetail += `: ${text || '응답 없음'}`;
            }
            throw new Error(errorDetail);
        }
        const clientsData = await response.json();
        memberListBody.innerHTML = '';
        if (!Array.isArray(clientsData)) throw new Error("API 응답 형식 오류");
        if (clientsData.length === 0) {
             memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center;">표시할 내역이 없습니다.</td></tr>`;
             return;
        }

        const processedPersonKeys = new Set();
        console.log(`[Plaint] Processing ${clientsData.length} clients.`);

        clientsData.forEach((clientInfo, index) => {
            const personName = clientInfo.name || '';
            const personPhone = clientInfo.phone || '';
            if (!personName || !personPhone) { console.warn(`Skipping client index ${index}: Missing name or phone.`); return; }
            const personKey = `${personName}-${personPhone}`;
            if (processedPersonKeys.has(personKey)) { console.log(`Skipping duplicate client entry: ${personKey}`); return; }
            processedPersonKeys.add(personKey);

            const clone = itemTemplate.content.cloneNode(true);
            const tableRow = clone.querySelector('tr.member-row');
            if (!tableRow) { console.error("Template 'tr.member-row' not found."); return; }
            const nameCell = tableRow.querySelector('.summary-name');
            const regionCell = tableRow.querySelector('.summary-region');
            const phoneCell = tableRow.querySelector('.summary-phone');
            const dateCell = tableRow.querySelector('.summary-date'); // 상담일
            const statusCell = tableRow.querySelector('.summary-status'); // 상태
            const documentsCell = tableRow.querySelector('.summary-documents'); // 서면 목록
            if (!nameCell || !regionCell || !phoneCell || !dateCell || !statusCell || !documentsCell) { console.error("One or more template cells not found."); return; }

            // --- ▼▼▼ 셀 내용 채우기 (수정됨) ▼▼▼ ---
            nameCell.textContent = personName || '정보 없음';
            regionCell.textContent = clientInfo.region || '정보 없음';
            phoneCell.textContent = personPhone || '정보 없음';

            // 1. 상담일: clientInfo.earliest_timestamp 사용 시도, 없으면 latest_timestamp 사용 (백엔드 확인 필요)
            let firstConsultDate = '정보 없음';
            const earliestTimestamp = clientInfo.earliest_timestamp || clientInfo.latest_timestamp; // earliest 우선
            if (!clientInfo.earliest_timestamp && clientInfo.latest_timestamp) console.warn(`[Plaint] earliest_timestamp missing for client ${personKey}, using latest_timestamp as fallback.`);
            try {
                if (earliestTimestamp) {
                    firstConsultDate = new Date(earliestTimestamp).toISOString().substring(0, 10);
                }
            } catch(e) { console.warn("Date parsing error for firstConsultDate", e); }
            dateCell.textContent = firstConsultDate;

            // 2. 상태: "수임"으로 고정
            statusCell.textContent = '수임';
            statusCell.className = 'summary-status status-수임'; // CSS 클래스도 고정

            // 3. 서면 목록: 가장 최신 서면의 종류(topic) 표시
            let latestDocumentTopic = '등록된 서면 없음';
            if (Array.isArray(clientInfo.documents) && clientInfo.documents.length > 0) {
                try {
                    const sortedDocuments = [...clientInfo.documents].sort((a, b) => {
                        const timestampA = a.timestamp || a.date_created || a.date || 0;
                        const timestampB = b.timestamp || b.date_created || b.date || 0;
                        const dateA = new Date(timestampA);
                        const dateB = new Date(timestampB);
                        if (isNaN(dateA.getTime())) return 1;
                        if (isNaN(dateB.getTime())) return -1;
                        return dateB - dateA;
                    });
                    if (sortedDocuments.length > 0 && sortedDocuments[0].topic) {
                        latestDocumentTopic = `${escapeHtml(sortedDocuments[0].topic)}`;
                    } else if (sortedDocuments.length > 0) {
                         latestDocumentTopic = '종류 정보 없음';
                    }
                } catch(sortError) {
                    console.error("Error sorting documents by date:", sortError, clientInfo.documents);
                    if (clientInfo.documents[0]?.topic) {
                         latestDocumentTopic = `[${escapeHtml(clientInfo.documents[0].topic)}] (정렬 오류)`;
                    } else {
                         latestDocumentTopic = '[최신 서면 조회 오류]';
                    }
                }
            }
             documentsCell.textContent = latestDocumentTopic;
             documentsCell.title = latestDocumentTopic;

            // --- ▲▲▲ 셀 내용 채우기 끝 ▲▲▲ ---

            const clientIdentifier = clientInfo.identifier;
            if (clientIdentifier) {
                tableRow.dataset.clientIdentifier = clientIdentifier;
                tableRow.dataset.displayName = `${personName} (${personPhone})`;
                tableRow.dataset.clientName = personName;
                tableRow.dataset.clientPhone = personPhone;
                tableRow.style.cursor = 'pointer';
                tableRow.title = `${personName || '정보 없음'} 상세 정보 보기`;

                tableRow.addEventListener('click', async (event) => {
                     const clickedRow = event.currentTarget;
                     const currentIdentifier = clickedRow.dataset.clientIdentifier;
                     const currentName = clickedRow.dataset.clientName;
                     const currentPhone = clickedRow.dataset.clientPhone;

                     if (activeDetailRow && activeDetailRow === clickedRow) { closeActiveDetailRow(); return; }
                     closeActiveDetailRow();

                     console.log(`[Plaint] Opening detail row for client: ${currentIdentifier}`);
                     clickedRow.classList.add('active-detail-row');
                     activeDetailRow = clickedRow;
                     const detailRow = document.createElement('tr'); detailRow.classList.add('detail-row-inserted');
                     const detailCell = document.createElement('td'); detailCell.colSpan = columnCount; detailCell.style.cssText = "padding: 15px; background-color: #f8f9fa; border-bottom: 1px solid #dee2e6;";
                     detailCell.innerHTML = `
                         <div class="detail-area-container" data-client-identifier="${escapeHtml(currentIdentifier)}" data-client-name="${escapeHtml(currentName)}" data-client-phone="${escapeHtml(currentPhone)}">
                             <h4 style="margin:0 0 15px 0; color:#333;">${escapeHtml(clickedRow.dataset.displayName)} 상세 정보</h4>
                             <div class="detail-item-section">
                                 <div class="detail-header-1st" data-target="transcript" style="cursor:pointer; font-weight:bold; padding: 8px 0; border-bottom: 1px solid #eee;">녹취록</div>
                                 <div id="transcript-content-${currentIdentifier}" class="detail-content-1st" style="display: none; padding-top: 10px;">로딩 중...</div>
                             </div>
                             <div class="detail-item-section">
                                 <div class="detail-header-1st" data-target="files" style="cursor:pointer; font-weight:bold; padding: 8px 0; border-bottom: 1px solid #eee;">증거파일</div>
                                 <div id="files-content-${currentIdentifier}" class="detail-content-1st" style="display: none; padding-top: 10px;">로딩 중...</div>
                             </div>
                             <div class="detail-item-section">
                                 <div class="detail-header-1st" data-target="documents" style="cursor:pointer; font-weight:bold; padding: 8px 0; border-bottom: 1px solid #eee;">모든 서면 목록</div>
                                 <div id="documents-content-${currentIdentifier}" class="detail-content-1st" style="display: none; padding-top: 10px;">로딩 중...</div>
                             </div>
                         </div>`;
                     detailRow.appendChild(detailCell);
                     clickedRow.parentNode.insertBefore(detailRow, clickedRow.nextSibling);

                     const detailAreaContainer = detailRow.querySelector('.detail-area-container');
                     detailRow.querySelectorAll('.detail-header-1st').forEach(header => {
                         header.addEventListener('click', async () => {
                             const targetContent = header.nextElementSibling;
                             if (!targetContent) return;
                             const isHidden = targetContent.style.display === 'none';

                             detailRow.querySelectorAll('.detail-content-1st').forEach(content => {
                                 if (content !== targetContent) { content.style.display = 'none'; content.previousElementSibling?.classList.remove('active-1st-header'); }
                             });
                             targetContent.style.display = isHidden ? 'block' : 'none';
                             header.classList.toggle('active-1st-header', isHidden);
                             console.log(`[Plaint] ${isHidden ? 'Opened' : 'Closed'} detail section: ${header.dataset.target}`);

                             if (isHidden && targetContent.innerHTML.includes('로딩 중...')) {
                                 const clientName = detailAreaContainer.dataset.clientName;
                                 const clientPhone = detailAreaContainer.dataset.clientPhone;
                                 const clientId = detailAreaContainer.dataset.clientIdentifier;
                                 const targetType = header.dataset.target;

                                 if (!currentUserToken_plaint) { targetContent.innerHTML = `<p style="color: red;">인증 토큰 없음</p>`; return; }

                                 try {
                                     if (targetType === 'documents') {
                                         const docsApi = `/api/admin/documents/all?client_identifier=${encodeURIComponent(clientId)}`;
                                         const res = await fetch(docsApi, { headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` } });
                                         if (!res.ok) throw new Error(`서버 오류 ${res.status}`);
                                         const data = await res.json();
                                         targetContent.innerHTML = renderCombinedDocumentListContent(data);
                                         targetContent.querySelectorAll('.combined-doc-header').forEach(h => {
                                             h.addEventListener('click', () => showInlineDocumentDetail(h.dataset.storageKey, h));
                                         });
                                     }
                                     else if (targetType === 'transcript' || targetType === 'files') {
                                         const filesApi = `/api/admin/files/list?name=${encodeURIComponent(clientName)}&phone=${encodeURIComponent(clientPhone)}`;
                                         const res = await fetch(filesApi, { headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` } });
                                         if (!res.ok) throw new Error(`서버 오류 ${res.status}`);
                                         const data = await res.json();
                                         if (!data || !Array.isArray(data.files)) throw new Error("파일 목록 형식 오류");

                                         const isLikelyAudio = (file) => {
                                             const audioTypes = ['audio/mpeg', 'audio/wav', 'audio/webm','audio/ogg', 'audio/mp3', 'audio/mp4', 'audio/m4a', 'audio/x-m4a', 'audio/aac', 'audio/flac'];
                                             const audioExtensions = ['.wav', '.mp3', '.m4a', '.ogg', '.aac', '.flac', '.mp4'];
                                             const fileTypeLower = (file.type || file.mime_type || '').toLowerCase();
                                             const fileNameLower = (file.original_filename || '').toLowerCase();
                                             if (fileTypeLower && audioTypes.some(t => fileTypeLower.startsWith(t))) return true;
                                             if (fileNameLower && audioExtensions.some(ext => fileNameLower.endsWith(ext))) return true;
                                             return false;
                                         };
                                         const filtered = (targetType === 'transcript') ? data.files.filter(isLikelyAudio) : data.files.filter(f => !isLikelyAudio(f));
                                         targetContent.innerHTML = renderFileListContent(filtered, targetType === 'transcript' ? '녹취록' : '증거파일');
                                     }
                                 } catch (error) {
                                     console.error(`Error loading ${targetType}:`, error);
                                     targetContent.innerHTML = `<p style="color: red;">${targetType} 로드 오류: ${escapeHtml(error.message)}</p>`;
                                 }
                             }
                         });
                     });
                });
             }

            memberListBody.appendChild(tableRow);
        });

        console.log(`[Plaint] Displayed ${processedPersonKeys.size} unique clients.`);

    } catch (error) {
        console.error(`[Plaint] Error during loadComplaints:`, error);
        memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center; color: red;">목록 로드 중 오류 발생: ${escapeHtml(error.message)}</td></tr>`;
    }
} // === End loadComplaints ===


// === 파일 다운로드 처리 함수 (물리적 파일용 - 변경 없음) ===
async function handleFileDownload(event) {
    const linkElement = event.target.closest('.download-link');
    if (!linkElement) { return; }

    console.log("### handleFileDownload function started! (For physical files)");
    event.preventDefault();

    const storageKey = linkElement.dataset.storageKey;
    const processedFilename = linkElement.dataset.processedFilename;
    const originalFilename = linkElement.dataset.originalFilename;
    console.log(`[Download] Attempting physical file download: ${originalFilename} (SK: ${storageKey}, PFN: ${processedFilename})`);

    if (!storageKey || !processedFilename || !currentUserToken_plaint) {
        alert('다운로드 정보 부족 또는 로그인이 필요합니다.');
        return;
    }

    const downloadUrl = `/api/admin/files/download?storageKey=${encodeURIComponent(storageKey)}&processedFilename=${encodeURIComponent(processedFilename)}`;
    const initialText = linkElement.textContent;

    try {
        linkElement.textContent = `${originalFilename} (다운로드 중...)`;
        linkElement.style.color = '#888';
        const response = await fetch(downloadUrl, {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` }
        });

        if (!response.ok) {
            let errorMsg = `다운로드 실패 (${response.status})`;
            let errorDetail = '서버 응답 없음';
             try {
                 const errorText = await response.text();
                 try {
                     const errorJson = JSON.parse(errorText);
                     errorDetail = errorJson.error || errorJson.detail || errorText;
                 } catch (parseError) { errorDetail = errorText || '응답 본문 읽기 실패'; }
             } catch (readError) { errorDetail = '서버 응답 읽기 오류'; }
             errorMsg += `: ${errorDetail}`;
             throw new Error(errorMsg);
         }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const tempLink = document.createElement('a');
        tempLink.href = url;
        tempLink.setAttribute('download', originalFilename || 'download');
        document.body.appendChild(tempLink);
        tempLink.click();
        document.body.removeChild(tempLink);
        window.URL.revokeObjectURL(url);
        console.log(`[Download] Successfully triggered physical file download for: ${originalFilename}`);
        linkElement.textContent = initialText;
        linkElement.style.color = '#007bff';

    } catch (error) {
        console.error('[Download] Error:', error);
        alert(`다운로드 중 오류 발생: ${error.message}`);
        linkElement.textContent = initialText;
        linkElement.style.color = '#007bff';
    }
}

// === DOM 로드 후 실행될 메인 로직 (변경 없음) ===
document.addEventListener('DOMContentLoaded', () => {
    console.log("[Plaint] DOMContentLoaded.");
    isFirebaseInitialized_plaint = (typeof firebase !== 'undefined' && firebase.apps.length > 0);

    const memberListBody = document.getElementById('member-list-body');
    const itemTemplate = document.getElementById('summary-row-template');
    if (!memberListBody || !itemTemplate || !itemTemplate.content) {
        console.error("[Plaint] CRITICAL: List/template elements missing!");
        return;
    }

    // 모달/Backdrop 리스너 설정
    const backdrop = document.getElementById('modalBackdrop');
    const documentDetailModal = document.getElementById('documentDetailModal');
    const docModalCloseBtn = documentDetailModal?.querySelector('.close-button');
    const closeModal = () => {
        if(documentDetailModal) documentDetailModal.style.display = 'none';
        if(backdrop) backdrop.classList.remove('active');
    };
    if (backdrop) { backdrop.addEventListener('click', closeModal); }
    if (docModalCloseBtn) { docModalCloseBtn.addEventListener('click', closeModal); }

    // --- ▼▼▼ 모달 내부 '물리 파일' 다운로드 링크 리스너 (handleFileDownload 호출용) ▼▼▼ ---
    if (documentDetailModal) {
        documentDetailModal.addEventListener('click', (event) => {
            const linkElement = event.target.closest('a.download-link');
            if (linkElement) {
                console.log("[Plaint Modal Download] Physical file download link clicked inside modal.");
                handleFileDownload(event);
            }
        });
        console.log("[Plaint] Physical file download listener attached to #documentDetailModal.");
    } else {
        console.error("[Plaint] Could not find #documentDetailModal to attach download listener.");
     }
    // --- ▲▲▲ 모달 리스너 완료 ▲▲▲ ---

    // 사이드바 토글 리스너
    const sidebarToggle = document.getElementById('sidebarToggle');
    const container = document.querySelector('.admin-container') || document.querySelector('.main-content-area');
    if (sidebarToggle && container) {
        sidebarToggle.addEventListener('click', () => {
            container.classList.toggle('sidebar-collapsed');
            console.log("Sidebar toggled.");
        });
    }

    // ★★★ 테이블 목록 내 '물리 파일' 다운로드 리스너 (handleFileDownload 호출용) ★★★
    if (memberListBody) {
        memberListBody.addEventListener('click', (event) => {
            if (event.target.closest('a.download-link')) {
                 handleFileDownload(event);
            }
        });
        console.log("[Plaint] Physical file download listener attached to #member-list-body.");
    } else {
        console.error("[Plaint] Could not find #member-list-body to attach download listener.");
    }
    // ★★★ 리스너 설정 완료 ★★★

    console.log("[Plaint] Event listeners set up. Waiting for Auth...");
}); // === End DOMContentLoaded ===


// === Firebase Auth 상태 변경 리스너 (변경 없음) ===
if (typeof firebase !== 'undefined' && typeof firebase.auth === 'function') {
    firebase.auth().onAuthStateChanged(user => {
        console.log("[Plaint Auth] State Changed. User:", user ? user.email : 'Logged out');
        const memberListBody = document.getElementById('member-list-body');
        if (!memberListBody) {
             console.log("[Plaint Auth] Not on plaint page, ignoring auth state change.");
             return;
        }
        isFirebaseInitialized_plaint = true;
        const documentDetailModal = document.getElementById('documentDetailModal');
        const backdrop = document.getElementById('modalBackdrop');

        if (user) {
            console.log("[Plaint Auth] User logged in. Loading complaints...");
             closeActiveDetailRow();
             closeDetailPanel();
             if (documentDetailModal) documentDetailModal.style.display = 'none';
             if (backdrop) backdrop.classList.remove('active');
             loadComplaints();
        } else {
             console.log("[Plaint Auth] User logged out.");
             const columnCount = memberListBody.closest('table')?.querySelector('thead th')?.length || 6;
             memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center;">로그인이 필요합니다.</td></tr>`;
             currentUserToken_plaint = null;
             closeActiveDetailRow();
             closeDetailPanel();
             if (documentDetailModal) documentDetailModal.style.display = 'none';
             if (backdrop) backdrop.classList.remove('active');
        }
    });
} else {
    console.error("[Plaint Auth] Firebase SDK not found or firebase.auth is not a function.");
    document.addEventListener('DOMContentLoaded', () => {
        const mb = document.getElementById('member-list-body');
        const columnCount = mb?.closest('table')?.querySelector('thead th')?.length || 6;
        if (mb) mb.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center; color: red;">Firebase SDK 로드 오류. 페이지 기능을 사용할 수 없습니다.</td></tr>`;
    });
}