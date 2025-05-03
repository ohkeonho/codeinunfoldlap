// script.js - 관리자 페이지 및 일반 업로드/녹음 페이지 공용 스크립트 (사이드바 토글 기능 통합)

// === 전역 변수 ===
let isFirebaseInitialized = false; // Firebase 초기화 상태
let currentAdminToken = null;     // 관리자 페이지에서 사용할 토큰 저장용 (다른 페이지에서는 사용 안 함)
let currentBackdrop = null;       // 모바일 백드롭 요소 (추가)


// === 유틸리티 함수 ===
function showLoading(indicatorElementId = 'loadingIndicator', message = '처리 중입니다...') {
    const indicator = document.getElementById(indicatorElementId);
    // adminUploadStatus는 오류/성공 메시지도 표시하므로 다른 요소 숨김 로직 일부 제외
    const errorIndicator = (indicatorElementId === 'adminUploadStatus') ? null : document.getElementById('errorIndicator');
    const resultsArea = (indicatorElementId === 'adminUploadStatus') ? null : document.getElementById('resultsArea');
    if (indicator) {
        indicator.textContent = message;
        indicator.style.display = 'block';
        indicator.className = 'status-loading'; // 로딩 상태 클래스
        if (errorIndicator) errorIndicator.style.display = 'none';
        if (resultsArea) resultsArea.style.display = 'none';
    } else { console.warn(`[Util] Loading indicator element ('${indicatorElementId}') not found.`); }
}

function hideLoading(indicatorElementId = 'loadingIndicator') {
    const indicator = document.getElementById(indicatorElementId);
    if (indicator) indicator.style.display = 'none';
}

function showError(indicatorElementId = 'errorIndicator', message) {
    const errorIndicator = document.getElementById(indicatorElementId);
    const loadingIndicator = (indicatorElementId === 'adminUploadStatus') ? errorIndicator : document.getElementById('loadingIndicator');
    const resultsArea = (indicatorElementId === 'adminUploadStatus') ? null : document.getElementById('resultsArea');
    if (errorIndicator) {
        errorIndicator.textContent = '오류: ' + message;
        errorIndicator.style.display = 'block';
        errorIndicator.className = 'status-error'; // 에러 상태 클래스
        if (loadingIndicator && loadingIndicator !== errorIndicator) hideLoading(loadingIndicator.id);
        if (resultsArea) resultsArea.style.display = 'none';
    } else {
        console.error(`[Util] Error display failed, element ('${indicatorElementId}') not found. Message:`, message);
        alert("오류: " + message);
    }
}

function showResults(originalTextDivId = 'originalText', summaryDivId = 'geminiSummary', originalText, summary) {
    // 이 함수는 주로 일반 업로드/녹음 페이지에서 사용
    const originalTextDiv = document.getElementById(originalTextDivId);
    const geminiSummaryDiv = document.getElementById(summaryDivId);
    const resultsArea = document.getElementById('resultsArea');
    const loadingIndicator = document.getElementById('loadingIndicator');
    const errorIndicator = document.getElementById('errorIndicator');
    if (originalTextDiv && geminiSummaryDiv && resultsArea && loadingIndicator && errorIndicator) {
        originalTextDiv.textContent = originalText || '원본 텍스트 없음';
        geminiSummaryDiv.textContent = summary || '요약 없음';
        resultsArea.style.display = 'block';
        hideLoading(loadingIndicator.id);
        errorIndicator.style.display = 'none';
    } else { console.error("[Util] Result display failed, elements not found."); }
}

// HTML 이스케이프 함수
const escapeHtml = (unsafe) => {
    if (typeof unsafe !== 'string') return '';
    return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
};


document.addEventListener("DOMContentLoaded", function() {
    document.getElementById("phoneInputUpload").addEventListener("keyup", function(event) {
        inputPhoneNumber(event.target);
    });
});
document.addEventListener("DOMContentLoaded", function() {
    document.getElementById("phoneInputRecord").addEventListener("keyup", function(event) {
        inputPhoneNumber(event.target);
    });
});

function inputPhoneNumber( phone ) {
    if( event.keyCode != 8 ) {
        const regExp = new RegExp( /^[0-9]{2,3}-^[0-9]{3,4}-^[0-9]{4}/g );
        if( phone.value.replace( regExp, "").length != 0 ) {                
            if( checkPhoneNumber( phone.value ) == true ) {
                let number = phone.value.replace( /[^0-9]/g, "" );
                let tel = "";
                let seoul = 0;
                if( number.substring( 0, 2 ).indexOf( "02" ) == 0 ) {
                    seoul = 1;
                    phone.setAttribute("maxlength", "12");
                    console.log( phone );
                } else {
                    phone.setAttribute("maxlength", "13");
                }
                if( number.length < ( 4 - seoul) ) {
                    return number;
                } else if( number.length < ( 7 - seoul ) ) {
                    tel += number.substr( 0, (3 - seoul ) );
                    tel += "-";
                    tel += number.substr( 3 - seoul );
                } else if(number.length < ( 11 - seoul ) ) {
                    tel += number.substr( 0, ( 3 - seoul ) );
                    tel += "-";
                    tel += number.substr( ( 3 - seoul ), 3 );
                    tel += "-";
                    tel += number.substr( 6 - seoul );
                } else {
                    tel += number.substr( 0, ( 3 - seoul ) );
                    tel += "-";
                    tel += number.substr( ( 3 - seoul), 4 );
                    tel += "-";
                    tel += number.substr( 7 - seoul );
                }
                phone.value = tel;
            } else {
                const regExp = new RegExp( /[^0-9|^-]*$/ );
                phone.value = phone.value.replace(regExp, "");
            }
        }
    }
}

function checkPhoneNumber( number ) {
    const regExp = new RegExp( /^[0-9|-]*$/ );
    if( regExp.test( number ) == true ) { return true; }
    else { return false; }
}

// === 관리자 페이지 주요 기능 함수 ===
function setupSidebarInteractions() {
    console.log("Setting up sidebar interactions...");

    // --- 필요한 요소 가져오기 ---
    const sidebar = document.querySelector('.sidebar');
    const adminContainer = document.querySelector('.admin-container'); // <<< adminContainer를 함수 내에서 찾도록 수정
    const thePinToggleButton = document.getElementById('sidebarPinToggle'); // HTML에 있는 실제 버튼 ID 사용
    const pinIcon = thePinToggleButton?.querySelector('i'); // 버튼 안의 아이콘 찾기

    // Check if all required elements exist
    if (thePinToggleButton && pinIcon && sidebar && adminContainer) { // <<< 모든 요소가 있는지 확인
        console.log("All elements found for sidebar interactions.");

        // 페이지 로드 시 초기 상태 설정 (하나의 버튼 기준으로)
        const isInitiallyFixed = sidebar.classList.contains('sidebar-fixed-expanded');
        if (!isInitiallyFixed) { // 고정되지 않은 상태 (호버 활성화 상태)
            adminContainer.classList.add('sidebar-hover-enabled');
            pinIcon.className = 'fas fa-thumbtack'; // 압정 아이콘
            thePinToggleButton.title = '사이드바 고정';
        } else { // 고정된 상태 (호버 비활성화 상태)
            adminContainer.classList.remove('sidebar-hover-enabled');
            pinIcon.className = 'fas fa-anchor'; // 닻 아이콘
            thePinToggleButton.title = '사이드바 호버 활성화';
        }
        console.log("Initial sidebar state setup complete. Fixed:", isInitiallyFixed, "Hover enabled:", !isInitiallyFixed);

        // 단일 토글 버튼 클릭 이벤트 (모든 동작 통합)
        thePinToggleButton.addEventListener('click', () => {
            console.log("#sidebarPinToggle CLICKED!"); // 클릭 로그

            // 클래스 토글 (사이드바 자체 & 컨테이너 동기화 & 호버 상태)
            sidebar.classList.toggle('sidebar-fixed-expanded');
            adminContainer.classList.toggle('sidebar-fixed-expanded'); // 컨테이너에도 고정 클래스 반영
            adminContainer.classList.toggle('sidebar-hover-enabled'); // 호버 가능 상태 반전

            // 아이콘 및 툴팁 업데이트 (클릭 *후*의 상태 기준)
            const isNowFixed = sidebar.classList.contains('sidebar-fixed-expanded');
            pinIcon.className = isNowFixed ? 'fas fa-anchor' : 'fas fa-thumbtack'; // 고정됨 -> 닻, 안됨 -> 압정
            thePinToggleButton.title = isNowFixed ? '사이드바 호버 활성화' : '사이드바 고정';

            // 상태 로그
            console.log('Sidebar classes after click:', sidebar.classList.toString());
            console.log('Admin container classes after click:', adminContainer.classList.toString());
            console.log(`Pin toggled. New Fixed state: ${isNowFixed}, Hover enabled: ${adminContainer.classList.contains('sidebar-hover-enabled')}`);
        });
        console.log("Event listener attached to #sidebarPinToggle.");

    } else {
        // 어떤 요소가 없는지 구체적으로 경고
        console.warn("Could not set up sidebar interactions: one or more required elements missing.");
        if (!thePinToggleButton) console.warn("- Button with ID 'sidebarPinToggle' not found.");
        if (!pinIcon) console.warn("- Icon element (i) inside '#sidebarPinToggle' not found.");
        if (!sidebar) console.warn("- Element with class '.sidebar' not found.");
        if (!adminContainer) console.warn("- Element with class '.admin-container' not found.");
    }
}
async function loadSummaries(user) {
    const memberListBody = document.getElementById('member-list-body');
    const itemTemplate = document.getElementById('member-row-template');
    const colspanValue = 6; // 이름, 지역, 번호, 상담일, 상태, 업로드버튼

    if (!memberListBody || !itemTemplate || !itemTemplate.content) {
        console.error("[Admin] loadSummaries: Required elements missing.");
        if(memberListBody) memberListBody.innerHTML = `<tr><td colspan="${colspanValue}">페이지 오류.</td></tr>`;
        return;
    }
    memberListBody.innerHTML = `<tr><td colspan="${colspanValue}" style="text-align: center;">의뢰인 목록 로딩 중...</td></tr>`;
    console.log("[Admin] Fetching summaries from /api/admin/summaries..."); // 관리자용 API 경로

    let idToken;
    try {
        const currentUser = firebase.auth().currentUser;
        if (!isFirebaseInitialized || !currentUser) { throw new Error("로그인 필요 또는 Firebase 미초기화"); }
        idToken = await user.getIdToken(true);
        currentAdminToken = idToken; // 토큰 저장 (상세보기용)
        console.log("[Admin] Admin ID Token acquired for list.");
    } catch (error) {
        console.error('[Admin] Failed to get admin ID token:', error);
        memberListBody.innerHTML = `<tr><td colspan="${colspanValue}" style="color:red; text-align:center;">인증 토큰 오류: ${error.message}</td></tr>`;
        currentAdminToken = null; return;
    }

    try {
        // 관리자용 API 호출 (백엔드에 /api/admin/summaries 구현 필요)
        const response = await fetch('/api/summaries', {
            method: 'GET',
            headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' }
        });

        if (!response.ok) {
             const text = await response.text();
             let errorDetail = '';
             try { const errJson = JSON.parse(text); errorDetail = errJson.error || errJson.detail || text;}
             catch(e){ errorDetail = text || 'N/A'; }
             throw new Error(`서버 오류 (${response.status}): ${errorDetail}`);
        }
        const summaries = await response.json().catch(err => { throw new Error("데이터 형식 오류"); });

        memberListBody.innerHTML = '';
        if (!Array.isArray(summaries)) { throw new Error("API 응답 형식이 배열 아님"); }
        if (summaries.length === 0) {
            memberListBody.innerHTML = `<tr><td colspan="${colspanValue}" style="text-align: center;">표시할 의뢰인 내역 없음.</td></tr>`; return;
        }
        console.log(`[Admin] Displaying ${summaries.length} summaries.`);

        summaries.forEach((summaryInfo, index) => {
             // ... (Row 생성 및 셀 가져오기) ...
             const clone = itemTemplate.content.cloneNode(true);
             const tableRow = clone.querySelector('tr.member-row');
             if (!tableRow) return;
             const nameCell = clone.querySelector('.summary-name');
             const regionCell = clone.querySelector('.summary-region');
             const phoneCell = clone.querySelector('.summary-phone');
             const dateCell = clone.querySelector('.summary-date');
             const statusCell = clone.querySelector('.summary-status');
             const adminUploadButton = clone.querySelector('.admin-upload-btn');
             if (!nameCell || !regionCell || !phoneCell || !dateCell || !statusCell || !adminUploadButton) return;

             // --- 셀 채우기 ---
             const displayName = summaryInfo.name || 'N/A';
             nameCell.textContent = displayName;
             regionCell.textContent = summaryInfo.region || 'N/A';
             phoneCell.textContent = summaryInfo.phone || 'N/A';
             const fullDateValue = summaryInfo.date_created || summaryInfo.timestamp || 'N/A';
             let displayDate = 'N/A';
             if (typeof fullDateValue === 'string' && fullDateValue.length >= 10) displayDate = fullDateValue.substring(0, 10);
             else displayDate = fullDateValue;
             dateCell.textContent = displayDate;
             let statusText = summaryInfo.status || '상태 미정'; let statusClass = 'status-unknown';
             const source = summaryInfo.source || 'unknown';
             if (summaryInfo.summary) statusText = "요약완료"; else statusText = "처리중";
             // source 기반 상태/클래스 업데이트
             if (source.includes('admin_upload_고소장')) { statusClass = 'status-admin status-complaint'; statusText = "고소장처리"; }
             else if (source.includes('admin_upload_보충이유서')) { statusClass = 'status-admin status-supplementary'; statusText = "보충서처리"; }
             else if (source.includes('admin_upload_검찰의견서')) { statusClass = 'status-admin status-prosecutor'; statusText = "검찰의견처리"; }
             else if (source.includes('admin_upload')) { statusClass = 'status-admin status-etc'; statusText = "관리자처리"; }
             else if (source.includes('upload')) { statusClass = 'status-upload'; }
             else if (source.includes('record')) { statusClass = 'status-record'; }
             statusCell.textContent = statusText; statusCell.className = `summary-status ${statusClass}`;

             // --- 데이터 저장 및 리스너 ---
             const storageKey = summaryInfo.storage_key;
             if (!storageKey) { tableRow.style.cursor='default'; }
             else {
                 tableRow.dataset.storageKey = storageKey;
                 tableRow.dataset.name = displayName;
                 tableRow.dataset.phone = summaryInfo.phone || '';
                 tableRow.dataset.region = summaryInfo.region || '';

                 // 업로드 버튼 리스너
                 adminUploadButton.addEventListener('click', (event) => {
                     event.stopPropagation();
                     openAdminModal(
                        tableRow.dataset.name,
                        tableRow.dataset.phone,
                        tableRow.dataset.region,
                        summaryInfo.user_email || '' 
                        );
                 });

                 // 행 클릭 리스너 (상세보기)
                 tableRow.style.cursor = 'pointer';
                 tableRow.addEventListener('click', () => {
                     const key = tableRow.dataset.storageKey;
                     const currentName = tableRow.dataset.name || 'N/A';
                     const currentPhone = tableRow.dataset.phone || 'N/A';
                     if (!key) return;
                     if (!currentAdminToken) { alert("인증 정보 만료. 다시 로그인해주세요."); return; }

                     const detailPanel = document.getElementById('detailPanel');
                     const detailPanelTitle = document.getElementById('detailPanelTitle');
                     const detailPanelContent = document.getElementById('detailPanelContent');
                     const backdrop = document.getElementById('modalBackdrop');
                     const container = document.querySelector('.admin-container');

                     if (!detailPanel || !detailPanelTitle || !detailPanelContent || !backdrop || !container) return;

                     // 패널 열기 및 로딩
                     detailPanelTitle.textContent = `${currentName} (${currentPhone}) - 로딩 중...`;
                     detailPanelContent.innerHTML = '<p style="text-align: center;">로딩 중...</p>';
                     detailPanel.classList.add('active'); backdrop.classList.add('active');
                     container.classList.add('detail-panel-active');

                     // 상세 정보 API 호출 (토큰 포함)
                     fetch(`/api/memory/${encodeURIComponent(key)}`, { headers: { 'Authorization': `Bearer ${currentAdminToken}` } })
                         .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
                         .then(data => {
                             detailPanelTitle.textContent = `${currentName} (${currentPhone}) - 요약 정보`;
                             const summaryContent = data.summary || '[요약 내용 없음]';
                             detailPanelContent.innerHTML = `<div style="white-space: pre-wrap; ; padding: 15px; border-radius: 5px; border: 1px solid #dee2e6;  height:720px; max-height: 100%; overflow-y: auto; line-height: 1.6; ">${escapeHtml(summaryContent)}</div>`;
                         })
                         .catch(error => {
                             console.error('[Admin] Error loading detail:', error);
                             detailPanelTitle.textContent = `${currentName} (${currentPhone}) - 오류`;
                             detailPanelContent.innerHTML = `<p style="color: red;">오류: ${error.message}</p>`;
                         });
                 }); // 행 클릭 리스너 끝
             } // storageKey 있을 때 else 끝
             memberListBody.appendChild(clone);
        }); // forEach 끝
    } catch (error) {
        console.error('[Admin] Error loading summary list:', error);
        memberListBody.innerHTML = `<tr><td colspan="${colspanValue}" style="color:red; text-align:center;">목록 로드 오류: ${error.message}</td></tr>`;
    }
} // --- End of loadSummaries ---

// 관리자 업로드 모달 열기 (모달 dataset에 정보 저장)
function openAdminModal(name, phone, region, email) {
     const modal = document.getElementById('adminUploadModal');
     const nameSpan = document.getElementById('modalClientName');
     const keySelect = document.getElementById('modalKeySelect');
     const audioInput = document.getElementById('modalAudioFile');
     const docInput = document.getElementById('modalDocumentFile');
     const statusDiv = document.getElementById('adminUploadStatus');
     const confirmBtn = document.getElementById('confirmUploadBtn');
     const backdrop = document.getElementById('modalBackdrop');

     if (!modal || !nameSpan || !keySelect || !audioInput || !docInput || !statusDiv || !confirmBtn || !backdrop) {
         console.error("[Admin] Cannot open admin modal - required elements missing."); alert("모달 요소 오류"); return;
     }

     // 모달 dataset에 정보 저장
     modal.dataset.clientName = name || '';
     modal.dataset.clientPhone = phone || '';
     modal.dataset.clientRegion = region || '';
     modal.dataset.clientEmail = email || '';

     // 표시 업데이트
     nameSpan.textContent = name || 'N/A';
     nameSpan.textContent = `${name || 'N/A'}`;
     // 폼 리셋
     keySelect.selectedIndex = 0;
    if (audioInput) audioInput.value = null;
    if (docInput) docInput.value = null;
     statusDiv.textContent = ''; statusDiv.className = '';
     confirmBtn.disabled = false; confirmBtn.textContent = '업로드 및 분석 시작';

     modal.style.display = 'block'; backdrop.classList.add('active');
 }

// 상세 패널 닫기
function closeDetailPanel() {
     const panel = document.getElementById('detailPanel');
     const backdrop = document.getElementById('modalBackdrop');
     const container = document.querySelector('.admin-container'); // admin.html 용
     if (panel) panel.classList.remove('active');
     const adminModal = document.getElementById('adminUploadModal');
     if (backdrop && (!adminModal || adminModal.style.display !== 'block')) backdrop.classList.remove('active');
     if (container) container.classList.remove('detail-panel-active');
}

// 관리자 업로드 모달 닫기
function closeAdminModal() {
     const modal = document.getElementById('adminUploadModal');
     const backdrop = document.getElementById('modalBackdrop');
     if(modal) modal.style.display = 'none';
     const detailPanel = document.getElementById('detailPanel');
     if (backdrop && (!detailPanel || !detailPanel.classList.contains('active'))) backdrop.classList.remove('active');
     if(modal) { delete modal.dataset.clientName; delete modal.dataset.clientPhone; delete modal.dataset.clientRegion; }
}

// 관리자 업로드 처리 (모달 dataset 사용 및 프론트 유효성 검사)
async function handleAdminUpload() {
     // 요소 가져오기
     const modal = document.getElementById('adminUploadModal');
     const modalAudioFile = document.getElementById('modalAudioFile');
     const modalDocumentFile = document.getElementById('modalDocumentFile');
     const modalKeySelectInModal = document.getElementById('modalKeySelect');
     const confirmUploadBtn = document.getElementById('confirmUploadBtn');
     const adminUploadStatus = document.getElementById('adminUploadStatus');

     if(!modal || !modalAudioFile || !modalDocumentFile || !modalKeySelectInModal || !confirmUploadBtn || !adminUploadStatus) {
         alert("업로드 처리 오류 (필수 요소 누락)"); return;
     }

     // 값 읽기 (파일 + 모달 dataset)
     const audioFile = modalAudioFile.files[0];
     const documentFiles = modalDocumentFile.files;
     const key = modalKeySelectInModal.value;
     const name = modal.dataset.clientName;
     const phone = modal.dataset.clientPhone;
     const region = modal.dataset.clientRegion;

     // 프론트엔드 유효성 검사
     let validationError = null;
     if (!name) { validationError = '대상 의뢰인 이름 정보 없음'; }
     else if (!phone) { validationError = '대상 의뢰인 연락처 정보 없음'; }
     else if (!region) { validationError = '대상 의뢰인 지역 정보 없음'; }
     else if (!key) { validationError = '주요 검토 사항(키워드) 선택 필요'; modalKeySelectInModal?.focus(); }
     else if (!audioFile) { validationError = '오디오 파일 선택 필요'; modalAudioFile?.focus(); }
     else if (!documentFiles || documentFiles.length === 0) { validationError = '문서 파일 1개 이상 선택 필요'; modalDocumentFile?.focus(); }
     else { /* 문서 확장자 검사 */
         const allowedExt = /(\.pdf|\.jpg|\.jpeg|\.png|\.bmp|\.tiff|\.gif|\.webp|\.ico)$/i;
         for(let f of documentFiles) if(!allowedExt.exec(f.name)){ validationError=`지원X:${f.name}`; break; }
     }
     if (validationError) { alert(validationError); return; }

     // 토큰 가져오기
     let uploaderToken;
     try {
         const currentUser = firebase.auth().currentUser; if (!currentUser) throw new Error("로그인 필요");
         uploaderToken = await currentUser.getIdToken(true);
     } catch(error) { showError('adminUploadStatus', `인증 오류: ${error.message}`); return; }

     // FormData 준비 및 UI 업데이트
     confirmUploadBtn.disabled = true; confirmUploadBtn.textContent = '처리 중...';
     showLoading('adminUploadStatus', `파일 ${documentFiles.length + 1}개 업로드 및 분석 시작...`);

     const formData = new FormData();
     formData.append('audioFile', audioFile, audioFile.name);
     for (let i = 0; i < documentFiles.length; i++) { formData.append('documentFiles', documentFiles[i], documentFiles[i].name); }
     formData.append('key', key); // key_topic 전달
     formData.append('name', name); // dataset에서 읽은 값
     formData.append('phone', phone); // dataset에서 읽은 값
     formData.append('region', region); // dataset에서 읽은 값

     // Fetch 요청 (백엔드 /admin/upload 경로 사용)
     fetch('/api/admin/upload', {
         method: 'POST',
         headers: { 'Authorization': `Bearer ${uploaderToken}` },
         body: formData
      })
     .then(response => response.json().then(data => ({ ok: response.ok, status: response.status, data })))
     .then(result => {
         if (!result.ok) { throw new Error(result.data.error || `서버 오류: ${result.status}`); }
         adminUploadStatus.textContent = result.data.message || `업로드 성공!`;
         adminUploadStatus.className = 'status-success';
         setTimeout(() => { loadSummaries(firebase.auth().currentUser); closeAdminModal(); }, 1800);
     })
     .catch(error => {
          showError('adminUploadStatus', error.message);
          confirmUploadBtn.disabled = false; confirmUploadBtn.textContent = '업로드 및 분석 시작';
      });
 } // --- End of handleAdminUpload ---


// === DOM 로드 후 실행될 메인 로직 ===
document.addEventListener('DOMContentLoaded', () => {
    console.log("DOMContentLoaded event fired. Initializing script...");
    // Firebase 초기화
    try {
        if (typeof firebase !== 'undefined' && firebase.initializeApp) {
            if (!firebase.apps.length) { firebase.initializeApp(firebaseConfig); console.log("Firebase Initialized."); }
            else { firebase.app(); console.log("Firebase already initialized."); }
            isFirebaseInitialized = true;
        } else { console.error("Firebase SDK not loaded!"); isFirebaseInitialized = false; }
    } catch (e) { console.error("Firebase init failed:", e); isFirebaseInitialized = false;}

    // === 관리자 페이지 요소가 있는지 확인하고 리스너 설정 ===
    const memberListBody = document.getElementById('member-list-body');
    if (memberListBody) { // 관리자 페이지 식별
        console.log("Setting up Admin page listeners...");
        const currentDetailPanel = document.getElementById('detailPanel');
        const currentBackdrop = document.getElementById('modalBackdrop');
        const sidebarToggle = document.getElementById('sidebarToggle');
        const adminContainer = document.querySelector('.admin-container');
        const adminUploadModal = document.getElementById('adminUploadModal');
        const confirmUploadBtn = document.getElementById('confirmUploadBtn');
        const modalCloseBtn = adminUploadModal?.querySelector('.close-detail-btn');
        const panelHeaderCloseButton = currentDetailPanel?.querySelector('.close-detail-btn');

        if (!currentDetailPanel || !currentBackdrop || !adminUploadModal || !confirmUploadBtn) {
             console.error("[Admin] Essential admin page elements missing!");
             if(memberListBody) memberListBody.innerHTML = `<tr><td colspan="6">페이지 구성 오류.</td></tr>`; // Colspan 수정
        } else {
             // 이벤트 리스너 설정
             currentBackdrop.addEventListener('click', () => { closeDetailPanel(); closeAdminModal(); });
             if (sidebarToggle && adminContainer) { sidebarToggle.addEventListener('click', () => adminContainer.classList.toggle('sidebar-collapsed')); } else { console.warn("Sidebar toggle/container missing.")}
             if (panelHeaderCloseButton) { panelHeaderCloseButton.addEventListener('click', closeDetailPanel); } else {console.warn("Panel close button missing.")}
             // 모달 닫기 버튼은 HTML onclick 대신 여기서 리스너 추가 (HTML의 onclick 제거 권장)
             if (modalCloseBtn) {
                  // modalCloseBtn.onclick = null; // 인라인 핸들러 제거 시도 (만약 있었다면)
                  modalCloseBtn.addEventListener('click', closeAdminModal);
              } else {console.warn("Modal close button missing.")}
             confirmUploadBtn.addEventListener('click', handleAdminUpload);
             console.log("[Admin] Event listeners set up. Waiting for auth state...");
        }
    } // --- End Admin Setup ---

    // === 일반 업로드/녹음 페이지 요소가 있는지 확인하고 리스너 설정 ===
    const uploadForm = document.getElementById('uploadForm');
    const startRecordingBtn = document.getElementById('startRecording');
    if (uploadForm || startRecordingBtn) { // 일반 페이지 식별
        console.log("Setting up Main page (upload/record) listeners...");
        const nameInputUpload = document.getElementById('nameInputUpload');
        const phoneInputUpload = document.getElementById('phoneInputUpload');
        const regionInputUpload = document.getElementById('regionInputUpload');
        const fileInput = document.getElementById('fileInput');
        const nameInputRecord = document.getElementById('nameInputRecord');
        const phoneInputRecord = document.getElementById('phoneInputRecord');
        const regionInputRecord = document.getElementById('regionInputRecord');
        const stopRecordingBtn = document.getElementById('stopRecording');

        let mediaRecorder; let audioChunks = []; // 녹음 변수

        // 파일 업로드 리스너
        if (uploadForm && nameInputUpload && phoneInputUpload && regionInputUpload && fileInput) {
            uploadForm.addEventListener('submit', async (event) => {
                event.preventDefault();
                if (!isFirebaseInitialized) { showError('errorIndicator', "Firebase 미초기화"); return; }
                // 유효성 검사
                if (!nameInputUpload.value || !phoneInputUpload.checkValidity() || !regionInputUpload.value || fileInput.files.length === 0) {
                    showError('errorIndicator', "이름, 전화번호(형식), 지역, 오디오 파일을 모두 입력/선택하세요."); return;
                }
                const name=nameInputUpload.value, phone=phoneInputUpload.value, region=regionInputUpload.value, audioFile=fileInput.files[0];
                // 토큰 가져오기
                const user = firebase.auth().currentUser; if (!user) { showError('errorIndicator', "로그인 필요"); return; }
                let idToken; try { showLoading('loadingIndicator','인증 확인중...'); idToken = await user.getIdToken(true); } catch (e) { showError('errorIndicator','토큰 오류'); hideLoading('loadingIndicator'); return; }
                // FormData 및 Fetch
                const formData = new FormData(); formData.append('file', audioFile); formData.append('name', name); formData.append('phone', phone); formData.append('region', region);
                showLoading('loadingIndicator','업로드 및 처리중...');
                try {
                    const response = await fetch('/api/upload', { method: 'POST', headers: { 'Authorization': `Bearer ${idToken}` }, body: formData });
                     if (!response.ok) { const errText = await response.text(); let errJson={}; try {errJson=JSON.parse(errText);}catch(e){} throw new Error(errJson.error||`서버 오류(${response.status})`); }
                     const data = await response.json();
                     if (data.error) { showError('errorIndicator', data.error+(data.detail?` (${data.detail})`:'')); } else { showResults('originalText','geminiSummary', data.original_text, data.summary); if(uploadForm) uploadForm.reset(); }
                } catch (error) { showError('errorIndicator', error.message); } finally { hideLoading('loadingIndicator'); }
            });
        } else if (uploadForm) { console.warn("[Main] Upload form or its inputs not found."); }

        // 녹음 리스너
        if (startRecordingBtn && stopRecordingBtn && nameInputRecord && phoneInputRecord && regionInputRecord) {
            startRecordingBtn.onclick = () => { /* ... 이전 녹음 시작 로직 ... */
                 if (!isFirebaseInitialized) { showError('errorIndicator', "Firebase 미초기화"); return; }
                 if (!nameInputRecord.value || !phoneInputRecord.checkValidity() || !regionInputRecord.value) { showError('errorIndicator', "녹음 전 정보 입력 필요"); return; }
                 const name=nameInputRecord.value, phone=phoneInputRecord.value, region=regionInputRecord.value; audioChunks = [];
                 navigator.mediaDevices.getUserMedia({ audio: true }).then(stream => {
                     let options={mimeType:'audio/webm'}; if (!MediaRecorder.isTypeSupported(options.mimeType)) options={mimeType:''};
                     try { mediaRecorder = new MediaRecorder(stream, options); } catch (e) { showError('errorIndicator',"녹음기 생성 실패"); return; }
                     mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
                     mediaRecorder.onstop = async () => { /* ... 이전 onstop 로직 (토큰 가져오기, fetch /record 호출 포함) ... */
                          stream.getTracks().forEach(t=>t.stop()); if(audioChunks.length === 0) { showError('errorIndicator', "녹음 데이터 없음"); startRecordingBtn.disabled=false; stopRecordingBtn.disabled=true; return; }
                          const blob = new Blob(audioChunks, {type: mediaRecorder.mimeType||'app/octet-stream'}); const ext = (mediaRecorder.mimeType||'').split('/')[1]?.split(';')[0]||'bin'; const file = new File([blob],`rec.${ext}`,{type:mediaRecorder.mimeType||'app/octet-stream'}); audioChunks=[];
                          const user=firebase.auth().currentUser; if(!user){showError('errorIndicator',"로그인 필요"); startRecordingBtn.disabled=false; stopRecordingBtn.disabled=true; return;}
                          let idToken; try{showLoading('loadingIndicator','인증 확인중...'); idToken = await user.getIdToken(true);}catch(e){showError('errorIndicator','토큰 오류');startRecordingBtn.disabled=false; stopRecordingBtn.disabled=true; hideLoading('loadingIndicator'); return;}
                          const formData = new FormData(); formData.append('file', file); formData.append('name', name); formData.append('phone', phone); formData.append('region', region);
                          showLoading('loadingIndicator','녹음 처리중...');
                          try { const resp = await fetch('/api/record', {method:'POST',headers:{'Authorization':`Bearer ${idToken}`},body:formData}); if(!resp.ok){const errD=await resp.json().catch(()=>({error:`HTTP ${resp.status}`}));throw new Error(errD.error||`서버 오류(${resp.status})`);} const data=await resp.json(); if(data.error){showError('errorIndicator',data.error+(data.detail?` (${data.detail})`:''));}else{showResults('originalText','geminiSummary',data.original_text, data.summary);} }
                          catch(error){showError('errorIndicator', error.message);} finally {startRecordingBtn.disabled=false; stopRecordingBtn.disabled=true; hideLoading('loadingIndicator');}
                      }; mediaRecorder.start(); startRecordingBtn.disabled = true; stopRecordingBtn.disabled = false;
                     const rA=document.getElementById('resultsArea'); if(rA)rA.style.display='none'; const eI=document.getElementById('errorIndicator'); if(eI)eI.style.display='none'; showLoading('loadingIndicator',"녹음 중...");
                 }).catch(e => { /* ... 마이크 오류 처리 ... */ showError('errorIndicator', '마이크 오류: '+e.message); startRecordingBtn.disabled = false; stopRecordingBtn.disabled = true; });
             };
            stopRecordingBtn.onclick = () => { if (mediaRecorder?.state === "recording") { mediaRecorder.stop(); showLoading('loadingIndicator', "처리 중..."); } };
        } else if (startRecordingBtn) { console.warn("[Main] Recording elements missing."); }

    } // --- End Main Page Setup ---

}); // === End DOMContentLoaded ===

// 전역 또는 접근 가능한 스코프에 캘린더 인스턴스 변수 선언
let miniCalendar = null;
// isFirebaseInitialized, firebase 객체, closeAdminModal 함수 등은
// 이 스크립트의 다른 부분이나 전역 스코프에서 사용 가능해야 합니다.
// (예: let isFirebaseInitialized = false; 스크립트 상단에 추가)

// === Helper 함수: 서버에 메모 추가 ===
async function addMemoToServer(dateStr, text) {
    if (typeof isFirebaseInitialized === 'undefined' || !isFirebaseInitialized || typeof firebase === 'undefined' || !firebase.auth().currentUser) {
        throw new Error("로그인 및 Firebase 초기화가 필요합니다.");
    }
    const idToken = await firebase.auth().currentUser.getIdToken(true); // Force refresh token
    const response = await fetch('/api/calendar/memos', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: dateStr, text: text })
    });
    if (!response.ok) { const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status} 오류` })); throw new Error(errorData.error || `메모 저장 실패 (${response.status})`); }
    return await response.json();
}

// === Helper 함수: 서버에서 메모 삭제 ===
async function deleteMemoFromServer(memoId) {
    if (typeof isFirebaseInitialized === 'undefined' || !isFirebaseInitialized || typeof firebase === 'undefined' || !firebase.auth().currentUser) { throw new Error("로그인 및 Firebase 초기화가 필요합니다."); }
    const idToken = await firebase.auth().currentUser.getIdToken(true); // Force refresh token
    const response = await fetch(`/api/calendar/memos/${encodeURIComponent(memoId)}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${idToken}` }
    });
    if (!response.ok) { const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status} 오류` })); throw new Error(errorData.error || `메모 삭제 실패 (${response.status})`); }
    return await response.json();
}

// === 오늘 날짜 문자열 (YYYY-MM-DD) 반환 함수 ===
function getTodayDateString() {
    const today = new Date();
    const year = today.getFullYear(); // 'yyyy'가 아니라 'year'로 변수 선언됨
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    // ▼▼▼ 오타 수정 ▼▼▼
    return `${year}-${month}-${day}`; // 'yyyy' 대신 'year' 사용
}

// === 특정 날짜의 메모 로드 및 표시 함수 ===
async function loadAndDisplayMemosForDate(dateStr) {
    const displayArea = document.getElementById('today-memo-display');
    const statusDiv = document.getElementById('memo-status');
    if (!displayArea) { console.error("Memo display area not found."); return; }

    displayArea.innerHTML = '<p>메모 로딩 중...</p>';
    if(statusDiv) { statusDiv.textContent = ''; statusDiv.className=''; }

    try {
        if (typeof firebase === 'undefined' || !firebase.auth().currentUser) { throw new Error("로그인이 필요합니다."); }
        const idToken = await firebase.auth().currentUser.getIdToken(true);
        const response = await fetch('/api/calendar/memos', { method: 'GET', headers: { 'Authorization': `Bearer ${idToken}` } });
        if (!response.ok) {
             let errorMsg = `메모 로딩 실패 (${response.status})`;
             try { const errData = await response.json(); errorMsg = errData.error || errData.detail || errorMsg; } catch(e) {}
             throw new Error(errorMsg);
         }
        const allMemos = await response.json();
        const memosForDate = allMemos.filter(memo => memo.start === dateStr);

        displayArea.innerHTML = '';
        if (memosForDate.length === 0) {
            displayArea.innerHTML = '<p>해당 날짜의 메모가 없습니다.</p>';
        } else {
            memosForDate.forEach(memo => {
                const memoP = document.createElement('p');
                const memoTextSpan = document.createElement('span');
                memoTextSpan.textContent = memo.title || "[내용 없음]";
                memoP.appendChild(memoTextSpan);
                const deleteBtn = document.createElement('button');
                deleteBtn.innerHTML = '<i class="fas fa-times"></i>';
                deleteBtn.classList.add('delete-memo-btn');
                deleteBtn.title = "메모 삭제";
                deleteBtn.dataset.memoId = memo.id;

                deleteBtn.addEventListener('click', async (e) => {
                    const memoIdToDelete = e.currentTarget.dataset.memoId;
                    if (confirm(`"${memo.title || '이 메모'}"를 삭제하시겠습니까?`)) {
                        try {
                            if(statusDiv) { statusDiv.textContent = "삭제 중..."; statusDiv.className=''; }
                            await deleteMemoFromServer(memoIdToDelete);
                            if(statusDiv) { statusDiv.textContent = "메모가 삭제되었습니다."; statusDiv.className='success'; }
                            loadAndDisplayMemosForDate(dateStr); // 목록 새로고침
                            if (miniCalendar) miniCalendar.refetchEvents(); // 캘린더 점 업데이트
                            setTimeout(()=> { if(statusDiv) { statusDiv.textContent = ''; statusDiv.className=''; } }, 2000);
                        } catch (error) {
                            console.error("Memo delete failed:", error);
                            if(statusDiv) { statusDiv.textContent = `삭제 오류: ${error.message}`; statusDiv.className='error'; }
                        }
                    }
                });
                memoP.appendChild(deleteBtn);
                displayArea.appendChild(memoP);
            });
        }
    } catch (error) {
        console.error("Error loading memos for date:", dateStr, error);
        displayArea.innerHTML = `<p style="color: red;">메모 로딩 중 오류 발생</p>`;
    }
}


// === DOM 로드 후 실행될 메인 로직 (캘린더 부분) ===
document.addEventListener('DOMContentLoaded', function() {
    // === 캘린더 및 메모 관련 요소 가져오기 ===
    const miniCalendarEl = document.getElementById('mini-calendar');
    const memoInputArea = document.getElementById('memo-input-area');
    const memoSelectedDateSpan = document.getElementById('memo-selected-date');
    const memoTextInput = document.getElementById('memo-text-input');
    const saveMemoBtn = document.getElementById('save-memo-btn');
    const cancelMemoBtn = document.getElementById('cancel-memo-btn');
    const memoStatusDiv = document.getElementById('memo-status');
    const refreshMemosBtn = document.getElementById('refresh-memos-btn');
    const modalBackdrop = document.getElementById('modalBackdrop');

    // --- 미니 캘린더 초기화 ---
    if (miniCalendarEl && memoInputArea && memoSelectedDateSpan && memoTextInput && saveMemoBtn && cancelMemoBtn && memoStatusDiv && refreshMemosBtn) {

        miniCalendar = new FullCalendar.Calendar(miniCalendarEl, {
            initialView: 'dayGridMonth', locale: 'ko', headerToolbar: {left:'prev,next', center:'title', right:''}, height:'auto', contentHeight:'auto', aspectRatio:1.2,

            // --- 이벤트 로드: 'events' 함수 (인증 헤더 추가) ---
            events: async function(fetchInfo, successCallback, failureCallback) {
                console.log("[MiniCal Events] Fetching events...");
                const currentUser = firebase.auth().currentUser;
                if (!currentUser) { successCallback([]); return; }
                try {
                    const idToken = await currentUser.getIdToken(true);
                    if (!idToken) throw new Error("Token is null");
                    const fetchUrl = `/api/calendar/memos?start=${fetchInfo.start.toISOString()}&end=${fetchInfo.end.toISOString()}`;
                    const response = await fetch(fetchUrl, { method: 'GET', headers: { 'Authorization': `Bearer ${idToken}` } });
                    if (!response.ok) throw new Error(`Server Error (${response.status})`);
                    const eventsArray = await response.json();
                    successCallback(eventsArray);
                } catch (error) {
                    console.error("[MiniCal Events] Fetch/Token Error:", error);
                    failureCallback(error);
                }
            },

            // --- 이벤트 점 표시 ---
            eventDidMount: function(info) {
                const dot = document.createElement('span');
                dot.style.cssText = 'background-color: #ff9f89; border-radius: 50%; width: 6px; height: 6px; display: inline-block; margin-left: 4px; vertical-align: middle;';
                const dayNumberEl = info.el.closest('.fc-daygrid-day')?.querySelector('.fc-daygrid-day-number');
                if (dayNumberEl && !dayNumberEl.querySelector('.memo-dot')) { dot.classList.add('memo-dot'); dayNumberEl.appendChild(dot); }
                info.el.style.display = 'none';
            },

            // --- 날짜 클릭: 해당 날짜 메모 로드 및 표시 ---
            dateClick: function(info) {
                console.log('Mini calendar date clicked:', info.dateStr);
                if (memoInputArea && memoSelectedDateSpan && memoTextInput && memoStatusDiv) {
                    memoSelectedDateSpan.textContent = info.dateStr;
                    memoInputArea.dataset.selectedDate = info.dateStr;
                    memoTextInput.value = '';
                    memoStatusDiv.textContent = ''; memoStatusDiv.className = '';
                    if(typeof loadAndDisplayMemosForDate === 'function') {
                        loadAndDisplayMemosForDate(info.dateStr);
                    }
                    memoInputArea.style.display = 'block';
                } else { console.error("Memo input elements missing on dateClick."); }
            },
        });
        // --- render() 호출은 Auth 상태 변경 시 ---
        console.log("FullCalendar instance created.");

        // --- 메모 저장 버튼 이벤트 리스너 (주석 해제 및 전체 코드 포함) ---
        saveMemoBtn.addEventListener('click', async () => {
            const dateStr = memoInputArea.dataset.selectedDate; // 선택된 날짜 가져오기
            const text = memoTextInput.value.trim(); // 입력된 메모 내용 가져오기

            // 입력 유효성 검사
            if (!dateStr) {
                 memoStatusDiv.textContent = "날짜가 선택되지 않았습니다.";
                 memoStatusDiv.className = 'error';
                 return;
            }
            if (!text) {
                 memoStatusDiv.textContent = "메모 내용을 입력하세요.";
                 memoStatusDiv.className = 'error';
                 memoTextInput.focus(); // 입력 필드에 포커스
                 return;
            }

            // 버튼 비활성화 및 상태 업데이트
            saveMemoBtn.disabled = true;
            cancelMemoBtn.disabled = true;
            memoStatusDiv.textContent = "저장 중...";
            memoStatusDiv.className = '';

            try {
                // 서버에 메모 추가 요청 (Helper 함수 사용)
                await addMemoToServer(dateStr, text);
                memoStatusDiv.textContent = "메모가 저장되었습니다.";
                memoStatusDiv.className = 'success';

                // 성공 시 입력 필드 비우고, 목록 및 캘린더 새로고침
                memoTextInput.value = ''; // 입력 필드 비우기
                if (typeof loadAndDisplayMemosForDate === 'function') {
                    loadAndDisplayMemosForDate(dateStr); // 현재 날짜 메모 목록 새로고침
                }
                if (miniCalendar) {
                    miniCalendar.refetchEvents(); // 캘린더의 점 표시 업데이트
                }

                // 성공 메시지 잠시 후 지우기
                setTimeout(() => {
                    if(memoStatusDiv) { memoStatusDiv.textContent = ''; memoStatusDiv.className = ''; }
                }, 2000);

            } catch (error) {
                // 오류 발생 시 처리
                console.error("Memo save failed:", error);
                if(memoStatusDiv) {
                    memoStatusDiv.textContent = `오류: ${error.message}`;
                    memoStatusDiv.className = 'error';
                }
            } finally {
                // 버튼 다시 활성화
                 saveMemoBtn.disabled = false;
                 cancelMemoBtn.disabled = false;
            }
        }); // saveMemoBtn 리스너 끝

        // --- 메모 취소 버튼 이벤트 리스너 ---
        cancelMemoBtn.addEventListener('click', () => {
             memoTextInput.value = ''; // 입력 필드만 비우기
             // 영역을 숨기거나 오늘 날짜로 되돌리지 않음 (현재 선택된 날짜 유지)
        });

        // --- 새로고침 버튼 리스너 ---
        refreshMemosBtn.addEventListener('click', () => {
            const currentDate = memoInputArea.dataset.selectedDate || getTodayDateString();
            console.log(`Refreshing memos for date: ${currentDate}`);
            if(typeof loadAndDisplayMemosForDate === 'function') {
                loadAndDisplayMemosForDate(currentDate); // 현재 날짜 메모 새로고침
            }
            if (miniCalendar) {
                miniCalendar.refetchEvents(); // 캘린더 점 새로고침
            }
        });

    } else { console.error("Calendar initialization skipped: Required elements missing."); }

    // --- 백드롭 클릭 리스너 (다른 모달용 - 캘린더 로직 없음) ---
    if (modalBackdrop) {
        modalBackdrop.addEventListener('click', function(event) {
            const adminModal = document.getElementById('adminUploadModal');
            if (event.target === modalBackdrop && adminModal && adminModal.style.display === 'block') {
                if (typeof closeAdminModal === 'function') {
                   closeAdminModal();
                }
            }
        });
    }

}); // === End DOMContentLoaded ===
// === Firebase Auth 상태 변경 리스너 ===
// === Firebase Auth 상태 변경 리스너 (캘린더 로직 추가) ===
if (typeof firebase !== 'undefined') {
    firebase.auth().onAuthStateChanged(user => {
        console.log("Auth State Changed. User:", user ? user.email : null);
        const memberListBody = document.getElementById('member-list-body'); // 관리자 페이지 식별

        // --- ▼▼▼ 메모 관련 DOM 요소 가져오기 (리스너 내에서) ▼▼▼ ---
        const memoInputArea = document.getElementById('memo-input-area');
        const memoSelectedDateSpan = document.getElementById('memo-selected-date');
        // --- ▲▲▲ 메모 관련 DOM 요소 가져오기 끝 ▲▲▲ ---

        // isFirebaseInitialized = true; // 필요 시 주석 해제 또는 다른 곳에서 관리

        if (user) { // 로그인 상태
            // --- ▼▼▼ 캘린더 렌더링/새로고침 로직 (기존 유지) ▼▼▼ ---
            if (typeof miniCalendar !== 'undefined' && miniCalendar) {
                console.log("[Auth State] User logged in. Attempting to render/refetch miniCalendar.");
                try {
                    miniCalendar.render();
                    miniCalendar.refetchEvents();
                } catch (error) {
                    console.error("[Auth State] Error during miniCalendar render/refetch:", error);
                }
            } else {
                if (typeof miniCalendar === 'undefined') { console.error("[Auth State] miniCalendar variable is not defined."); }
                else { console.warn("[Auth State] miniCalendar instance is null on login."); }
            }
            // --- ▲▲▲ 캘린더 로직 끝 ▲▲▲ ---

            // --- ▼▼▼ 오늘 날짜 설정 및 메모 로드 로직 추가 ▼▼▼ ---
            if (memoInputArea && memoSelectedDateSpan) { // 관련 요소들이 있는지 확인
                try {
                    const today = getTodayDateString(); // 오늘 날짜 계산 (YYYY-MM-DD)
                    console.log("[Auth State] Setting default date to:", today);

                    memoSelectedDateSpan.textContent = today; // ★ 헤더의 날짜 업데이트 ★
                    memoInputArea.dataset.selectedDate = today; // 내부적으로 날짜 저장
                    memoInputArea.style.display = 'block';      // 메모 영역 표시 확인

                    // 오늘 날짜의 메모 로드 함수 호출 (loadAndDisplayMemosForDate 함수는 정의되어 있어야 함)
                    if (typeof loadAndDisplayMemosForDate === 'function') {
                        console.log("[Auth State] Calling loadAndDisplayMemosForDate for today.");
                        loadAndDisplayMemosForDate(today);
                    } else {
                        console.error("[Auth State] loadAndDisplayMemosForDate function is not defined.");
                    }
                } catch (e) {
                    console.error("[Auth State] Error setting today's date or loading memos:", e);
                }
            } else {
                console.error("[Auth State] Cannot set today's date. Memo area elements not found.");
            }
            // --- ▲▲▲ 오늘 날짜/메모 로직 추가 완료 ▲▲▲ ---

            // --- 기존 로직 유지 (관리자 페이지 테이블 로드 등) ---
            if (memberListBody) { // 관리자 페이지
                console.log("User logged in on Admin page. Calling loadSummaries().");
                if (typeof loadSummaries === 'function') {
                    loadSummaries(user);
                } else {
                    console.error("loadSummaries function is not defined.");
                }
            } else { // 다른 페이지
                console.log("User logged in, not on Admin page.");
            }
            // --- 기존 로직 끝 ---

        } else { // 로그아웃 상태
             // --- ▼▼▼ 캘린더 이벤트 제거 로직 (기존 유지) ▼▼▼ ---
             if (typeof miniCalendar !== 'undefined' && miniCalendar) {
                 if (miniCalendar.el && miniCalendar.el.classList.contains('fc-rendered')) {
                     console.log("[Auth State] User logged out. Removing events from miniCalendar.");
                     miniCalendar.removeAllEvents();
                 }
             }
             // --- ▲▲▲ 캘린더 로직 끝 ▲▲▲ ---

             // --- ▼▼▼ 로그아웃 시 메모 영역 숨기기 추가 ▼▼▼ ---
             if (memoInputArea) { // 메모 영역 요소가 있으면 숨김
                 memoInputArea.style.display = 'none';
                 console.log("[Auth State] Memo area hidden on logout.");
             }
             // --- ▲▲▲ 숨기기 로직 추가 완료 ▲▲▲ ---

            // --- 기존 로직 유지 (테이블 비우기, 토큰 초기화 등) ---
            if (memberListBody) { // 관리자 페이지
                console.log("User logged out on Admin page.");
                memberListBody.innerHTML = `<tr><td colspan="6" style="text-align: center;">로그인이 필요합니다.</td></tr>`;
            } else { // 다른 페이지
                console.log("User logged out, not on Admin page.");
            }
            if (typeof currentAdminToken !== 'undefined') {
                 currentAdminToken = null;
            }
            // --- 기존 로직 끝 ---
        }
    });
} else {
    console.error("Firebase object not found for Auth listener.");
}