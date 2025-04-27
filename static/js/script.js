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

document.addEventListener('DOMContentLoaded', function() {
    const miniCalendarEl = document.getElementById('mini-calendar');
    const modalCalendarEl = document.getElementById('fullcalendar-modal');
    const calendarModal = document.getElementById('calendarModal');
    const modalBackdrop = document.getElementById('modalBackdrop');
    const closeCalendarModalBtn = document.getElementById('closeCalendarModal');

    // --- 미니 캘린더 초기화 ---
    if (miniCalendarEl) {
        miniCalendar = new FullCalendar.Calendar(miniCalendarEl, {
            initialView: 'dayGridMonth', // 월간 뷰
            locale: 'ko', // 한국어
            headerToolbar: { // 툴바 설정 (간소화)
                left: 'prev,next',
                center: 'title',
                right: '' // 버튼 숨김
            },
            events: '/api/events', // 이벤트 소스 (Flask 백엔드에서 제공해야 함)
            height: 'auto', // 높이 자동 조절 (작은 크기에 맞게)
            contentHeight: 'auto', // 콘텐츠 높이 자동 조절
            aspectRatio: 1.2, // 너비/높이 비율 조정 (작은 캘린더에 적합)
            eventDisplay: 'none', // 미니 캘린더에서는 이벤트 표시 안 함 (선택 사항)
                                 // 'list-item' 등으로 설정하여 간단히 표시 가능

            // 미니 캘린더 날짜 또는 배경 클릭 시 모달 열기
            dateClick: function(info) {
                 // 클릭한 날짜 정보를 가지고 모달 열기
                 openCalendarModal(info.date);
            },
             // 툴바 포함 미니 캘린더 영역 전체 클릭 시 모달 열기 (dateClick과 함께 사용 시 클릭 범위가 넓어짐)
            /*
             DidMount: function(info) {
                 info.el.addEventListener('click', function(event) {
                     // 이벤트 버블링 방지 (필요시)
                     // event.stopPropagation();
                     // dateClick 이벤트와 중복될 수 있으니 주의하여 사용
                     if (!event.target.closest('.fc-daygrid-day-number') && !event.target.closest('.fc-button')) {
                          // 날짜 숫자나 버튼 클릭이 아닌 경우에만 모달 열기
                           openCalendarModal(miniCalendar.getDate()); // 현재 미니 달력의 날짜로 열기
                     }
                 });
            }
            */
        });
        miniCalendar.render(); // 미니 캘린더 바로 렌더링
    } else {
        console.error("Mini calendar container element not found!");
    }

    // --- 큰 캘린더 (모달용) 초기화 ---
    if (modalCalendarEl) {
         modalCalendar = new FullCalendar.Calendar(modalCalendarEl, {
            initialView: 'dayGridMonth', // 기본 뷰
            locale: 'ko', // 한국어
             headerToolbar: { // 큰 달력에는 전체 툴바 표시
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,timeGridWeek,timeGridDay' // 뷰 전환 버튼
            },
            events: '/api/events', // 동일한 이벤트 소스 사용
            editable: true, // 이벤트 드래그, 리사이즈 등 편집 가능 여부 (필요 시)
            selectable: true, // 날짜/시간 범위 선택 가능 여부 (필요 시)
            height: 'auto', // 모달 높이에 맞게 자동 조절
            // aspectratio: 1.8, // 너비/높이 비율 조절

            // 이벤트 클릭 시 상세 정보 표시 (이전 예시 참고)
             eventClick: function(info) {
                 console.log('Event clicked:', info.event);
                 // alert('Event: ' + info.event.title + '\nStarts: ' + info.event.start.toLocaleString());
                 // 여기에 이벤트 상세 정보를 보여주는 모달이나 패널을 띄우는 로직 구현
             },
              // 날짜 선택 시 이벤트 추가 등 (필요 시)
            select: function(info) {
                console.log('Date range selected:', info.startStr, info.endStr, info.allDay);
                // const eventTitle = prompt('새 이벤트 제목:');
                // if (eventTitle) {
                //     // FullCalendar에 이벤트 임시 추가
                //     modalCalendar.addEvent({
                //         title: eventTitle,
                //         start: info.startStr,
                //         end: info.endStr, // FullCalendar는 끝 날짜/시간 포함
                //         allDay: info.allDay
                //     });
                //     // TODO: 이벤트를 백엔드에 저장하는 API 호출 필요
                // }
            },
            // 이벤트 드래그/리사이즈 후 업데이트 (editable: true 시)
             eventDrop: function(info) {
                 console.log('Event dropped:', info.event);
                 // TODO: 백엔드에 이벤트 시간/날짜 변경 API 호출 필요
             },
             eventResize: function(info) {
                 console.log('Event resized:', info.event);
                 // TODO: 백엔드에 이벤트 시간/날짜 변경 API 호출 필요
             },

             // 캘린더 뷰 변경 시 (예: 월 -> 주로 이동)
             viewDidMount: function(info) {
                 console.log('View changed to:', info.view.type);
                 // 필요하다면 뷰 변경 시 추가 로직 수행
             }
        });
        // modalCalendar.render(); // !! 모달이 열릴 때 렌더링하므로 여기서 바로 호출하지 않음
    } else {
         console.error("Modal calendar container element not found!");
    }

    // --- 모달 열기/닫기 함수 및 이벤트 핸들러 ---

    // 모달 열기 함수
    function openCalendarModal(initialDate = null) {
        // 모달과 백드롭 표시
        calendarModal.style.display = 'block';
        modalBackdrop.style.display = 'block';
        // 필요시 애니메이션 클래스 추가
        // calendarModal.classList.add('is-visible');
        // modalBackdrop.classList.add('is-visible');


        // 모달이 열릴 때 큰 달력 렌더링 또는 크기 업데이트
        if (modalCalendar) {
             // 중요: 모달이 보이게 된 후에 렌더링 또는 updateSize 호출
             if (!modalCalendar.el.hasChildNodes() || modalCalendar.getEvents().length === 0) {
                 // 처음 렌더링되거나 이벤트가 없는 경우 render() (필요시)
                 // 보통은 updateSize() 만으로 충분
                 // modalCalendar.render(); // 일반적으로 필요 없음
                  modalCalendar.updateSize(); // 필수: 모달 크기에 맞춰 캘린더 크기 조정
             } else {
                 // 이미 렌더링되었다면 크기만 업데이트
                 modalCalendar.updateSize(); // 필수
             }

            // 초기 날짜가 지정되었다면 해당 날짜로 이동
            if (initialDate) {
                modalCalendar.gotoDate(initialDate);
            } else if (miniCalendar) {
                // 초기 날짜가 없으면 미니 캘린더의 현재 뷰 날짜로 이동
                 modalCalendar.gotoDate(miniCalendar.getDate());
            }

            // 이벤트 데이터 새로고침 (필요시)
            // modalCalendar.refetchEvents();
        }
    }

    // 모달 닫기 함수
    function closeCalendarModal() {
        // 모달과 백드롭 숨김
        calendarModal.style.display = 'none';
        modalBackdrop.style.display = 'none';
         // 필요시 애니메이션 클래스 제거 또는 hidden 클래스 추가
        // calendarModal.classList.remove('is-visible');
        // modalBackdrop.classList.remove('is-visible');
        // calendarModal.classList.add('is-hidden'); // 애니메이션용
        // modalBackdrop.classList.add('is-hidden'); // 애니메이션용

        // FullCalendar 인스턴스는 메모리에 유지
        // 모달 닫을 때마다 완전히 파괴하고 싶다면 modalCalendar.destroy(); 호출 후
        // 열 때 새로 new FullCalendar.Calendar(...) 해야 함. 일반적으로 유지하는 것이 효율적.
    }

    // 닫기 버튼 클릭 이벤트
    if (closeCalendarModalBtn) {
        closeCalendarModalBtn.addEventListener('click', closeCalendarModal);
    }

    // 모달 백드롭 클릭 시 닫기
    if (modalBackdrop) {
        modalBackdrop.addEventListener('click', function(event) {
            // 백드롭 자체가 클릭되었는지 확인 (모달 콘텐츠 내부 클릭 무시)
             // calendarModal이 현재 표시되어 있는지 확인
            if (event.target === modalBackdrop && calendarModal.style.display === 'block') {
                 // 상세 업로드 모달 등 다른 모달과 백드롭을 공유하는 경우
                 // 어떤 모달이 열려있는지 확인하는 로직 추가 필요
                 // 예: if (calendarModal.style.display === 'block') closeCalendarModal();
                 // else if (adminUploadModal.style.display === 'block') closeAdminModal();
                 closeCalendarModal(); // 현재는 캘린더 모달만 닫도록 처리
            }
        });
    }

    // 미니 캘린더 컨테이너 자체 클릭 시 모달 열기
    // dateClick 이벤트와 함께 사용하면 클릭 범위가 넓어집니다.
    // 특정 영역(예: 제목) 클릭 시만 열고 싶다면 해당 요소에 이벤트 리스너 추가
    if (miniCalendarEl) {
         miniCalendarEl.addEventListener('click', function(event) {
             // FullCalendar의 내부 클릭 이벤트(dateClick, button click 등)와의 충돌 방지
             // 이벤트가 이미 FullCalendar 내부에서 처리되었으면 모달 열지 않음
             // (예: 날짜 셀 클릭이나 버튼 클릭 시 dateClick 이벤트가 먼저 발생)
             // 만약 dateClick 이벤트에서 모달을 열고 있다면 이 부분은 제거하거나 조건을 더 구체적으로 작성
             // 여기서는 dateClick에서 모달을 열도록 하므로, 이 리스너는 제거하거나 주석 처리하는 것이 좋습니다.
             // openCalendarModal(miniCalendar.getDate());
              // console.log("Mini calendar element clicked, opening modal");
         });
    }

    // --- 기타 페이지 초기화 로직 ---
    // 예: 테이블 데이터 로드 함수 호출
    // fetchMembers();
});
// === Firebase Auth 상태 변경 리스너 ===
if (typeof firebase !== 'undefined') {
    firebase.auth().onAuthStateChanged(user => {
        console.log("Auth State Changed. User:", user ? user.email : null);
        const memberListBody = document.getElementById('member-list-body'); // 관리자 페이지 식별

        isFirebaseInitialized = true; // 리스너 실행 시 초기화 완료 간주

        if (user) { // 로그인 상태
            if (memberListBody) { // 관리자 페이지
                console.log("User logged in on Admin page. Calling loadSummaries().");
                loadSummaries(user);
            } else { // 다른 페이지
                console.log("User logged in, not on Admin page.");
            }
        } else { // 로그아웃 상태
             if (memberListBody) { // 관리자 페이지
                 console.log("User logged out on Admin page.");
                 memberListBody.innerHTML = `<tr><td colspan="6" style="text-align: center;">로그인이 필요합니다.</td></tr>`; // Colspan 수정
             } else { // 다른 페이지
                 console.log("User logged out, not on Admin page.");
             }
             currentAdminToken = null; // 토큰 초기화
        }
    });
} else { console.error("Firebase object not found for Auth listener."); }