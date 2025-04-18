// plaint.js - 검창의견서 목록 페이지 스크립트

// === 전역 변수 ===
let isFirebaseInitialized_plaint = false; // 이 페이지의 Firebase 초기화 상태
let currentUserToken_plaint = null;     // 이 페이지에서 사용할 현재 사용자 토큰

// === 유틸리티 함수 ===
function closeDetailPanel() {
    console.log("Closing detail panel (called from plaint.js)...");
    const panel = document.getElementById('detailPanel');
    const backdrop = document.getElementById('modalBackdrop');
    // '.admin-container' 또는 '.main-content-area' 등 페이지 구조에 맞는 클래스 사용
    const container = document.querySelector('.admin-container') || document.querySelector('.main-content-area');

    if (panel) panel.classList.remove('active');
    if (backdrop) backdrop.classList.remove('active');
    // 페이지 레이아웃에 맞게 클래스 제거
    if (container) container.classList.remove('detail-panel-active');
}

// HTML 이스케이프 함수
const escapeHtml = (unsafe) => {
    if (typeof unsafe !== 'string') return '';
    return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
};

// === 검창의견서 목록 로드 함수 (async 추가 및 토큰 로직 포함) ===
async function loadComplaints() {
    const memberListBody = document.getElementById('member-list-body');
    const itemTemplate = document.getElementById('summary-row-template'); // HTML ID 확인!
    const columnCount = 5; // HTML 테이블 컬럼 수 확인! (예: 이름, 지역, 번호, 날짜, 상태)

    if (!memberListBody || !itemTemplate || !itemTemplate.content) {
        console.error("CRITICAL (plaint.js): Required elements missing for loadComplaints.");
        if(memberListBody) memberListBody.innerHTML = `<tr><td colspan="${columnCount}">페이지 오류 (요소 누락).</td></tr>`;
        return;
    }
    memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center; padding: 20px;">검창의견서 목록 로딩 중...</td></tr>`;

    let idToken;
    try {
        // --- ▼▼▼ 토큰 가져오기 로직 ▼▼▼ ---
        const currentUser = firebase.auth().currentUser;
        if (!isFirebaseInitialized_plaint || !currentUser) { // 초기화 및 로그인 확인
            throw new Error("로그인이 필요하거나 Firebase 초기화 문제입니다.");
        }
        console.log("[Plaint] Getting ID token...");
        idToken = await currentUser.getIdToken(true); // 토큰 가져오기 (필요시 갱신)
        currentUserToken_plaint = idToken; // 전역 변수에 저장 (상세보기용)
        console.log("[Plaint] ID Token acquired.");
        // --- ▲▲▲ 토큰 가져오기 로직 ▲▲▲ ---
    } catch (error) {
        console.error('[Plaint] Failed to get ID token:', error);
        memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align:center; color:red;">인증 토큰 오류: ${error.message}</td></tr>`;
        currentUserToken_plaint = null; // 토큰 초기화
        return; // 중단
    }

    const listApiEndpoint = '/api/prosecutor'; // 검창의견서 목록 API 경로
    console.log(`Workspaceing complaints from ${listApiEndpoint} (plaint.js)...`);

    try {
        // --- ▼▼▼ fetch 호출 시 헤더 추가 ▼▼▼ ---
        const response = await fetch(listApiEndpoint, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${idToken}`, // <<< 토큰 추가
                'Content-Type': 'application/json'
            }
        });
        // --- ▲▲▲ fetch 호출 시 헤더 추가 ▲▲▲ ---

        if (!response.ok) {
             const text = await response.text(); let errorDetail = '';
             try { const errJson = JSON.parse(text); errorDetail = errJson.error || errJson.detail || text;} catch(e){ errorDetail = text || 'N/A'; }
             throw new Error(`서버 오류 (${response.status}): ${errorDetail}`);
        }
        const summaries = await response.json().catch(err => { throw new Error("데이터 형식 오류"); });

        memberListBody.innerHTML = '';
        if (!Array.isArray(summaries)) { throw new Error("API 응답 형식이 배열 아님"); }
        if (summaries.length === 0) {
            memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center;">표시할 검창의견서 내역 없음.</td></tr>`; return;
        }
        console.log(`Displaying ${summaries.length} complaints (plaint.js).`);

        summaries.forEach((summaryInfo, index) => {
            if (index === 0) console.log("First complaint summaryInfo:", JSON.stringify(summaryInfo, null, 2));

            const clone = itemTemplate.content.cloneNode(true);
            const tableRow = clone.querySelector('tr.member-row'); // 템플릿 선택자 확인!
            if (!tableRow) { console.warn(`Template TR missing for item ${index}.`); return; }

            // 셀 가져오기 및 채우기 (클래스명 확인!)
            const nameCell = clone.querySelector('.summary-name');
            const regionCell = clone.querySelector('.summary-region');
            const phoneCell = clone.querySelector('.summary-phone');
            const dateCell = clone.querySelector('.summary-date');
            const statusCell = clone.querySelector('.summary-status');
            if (!nameCell || !regionCell || !phoneCell || !dateCell || !statusCell) { console.warn(`Skipping row ${index}: missing cells.`); return; }
            const displayName = summaryInfo.name || 'N/A';
            nameCell.textContent = displayName;
            regionCell.textContent = summaryInfo.region || 'N/A';
            phoneCell.textContent = summaryInfo.phone || 'N/A';
            const fullDateValue = summaryInfo.date_created || 'N/A'; // API 필드명 확인!
            let displayDate = 'N/A'; if (typeof fullDateValue === 'string' && fullDateValue.length >= 10) displayDate = fullDateValue.substring(0, 10); else displayDate = fullDateValue;
            dateCell.textContent = displayDate;
            const currentStatus = summaryInfo.status || '수임'; // API 필드명 확인!
            statusCell.textContent = currentStatus; statusCell.className = 'summary-status';
            const statusClassName = `status-${currentStatus.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`; statusCell.classList.add(statusClassName);

            // 상세 보기 설정
            const storageKey = summaryInfo.storage_key; // API 필드명 확인!
            if (!storageKey) { tableRow.style.cursor = 'default'; tableRow.title = '키 없음'; }
            else {
                 tableRow.dataset.storageKey = storageKey;
                 tableRow.dataset.displayname = displayName;
                 tableRow.style.cursor = 'pointer'; tableRow.title = '상세 분석 보기';

                 tableRow.addEventListener('click', () => { // 상세 보기 클릭 리스너
                     const key = tableRow.dataset.storageKey;
                     const nameForTitle = tableRow.dataset.displayname || "상세 정보";
                     if (!key) return;

                     // --- ▼▼▼ 상세 보기 시 토큰 확인 ▼▼▼ ---
                     if (!currentUserToken_plaint) {
                         alert("인증 정보가 없습니다. 다시 로그인해주세요."); return;
                     }
                     // --- ▲▲▲ 상세 보기 시 토큰 확인 ▲▲▲ ---

                     const detailApiEndpoint = `/api/memory/${encodeURIComponent(key)}`;
                     console.log(` -> Fetching details from: ${detailApiEndpoint} (plaint.js)`);

                     const detailPanel = document.getElementById('detailPanel');
                     const detailPanelTitle = document.getElementById('detailPanelTitle');
                     const detailPanelContent = document.getElementById('detailPanelContent');
                     const backdrop = document.getElementById('modalBackdrop');
                     const container = document.querySelector('.admin-container') || document.querySelector('.main-content-area');

                     if (!detailPanel || !detailPanelTitle || !detailPanelContent || !backdrop) { console.error("Detail panel elements missing."); return; }

                     // 패널 열기 및 로딩
                     detailPanelTitle.textContent = `${nameForTitle} - 상세 분석 로딩 중...`;
                     detailPanelContent.innerHTML = '<p style="text-align: center;">로딩 중...</p>';
                     detailPanel.classList.add('active'); backdrop.classList.add('active');
                     if (container) container.classList.add('detail-panel-active');

                     // --- ▼▼▼ 상세 데이터 Fetch 시 헤더 추가 ▼▼▼ ---
                     fetch(detailApiEndpoint, {
                         headers: { 'Authorization': `Bearer ${currentUserToken_plaint}` } // <<< 토큰 사용
                     })
                     .then(res => { /* ... 응답 처리 ... */
                         if (!res.ok) { return res.json().catch(()=>({error:`HTTP ${res.status}`})).then(e => {throw new Error(e.error);}); }
                         return res.json();
                      })
                     .then(data => { /* ... 상세 내용(요약) 표시 ... */
                          console.log("Detail data received:", data);
                          detailPanelTitle.textContent = `${nameForTitle} - 상세 분석 정보`;
                          const analysisContent = data.summary || '[표시할 분석 내용 없음]';
                          const escapedContent = escapeHtml(analysisContent);
                          detailPanelContent.innerHTML = `<div style="white-space: pre-wrap; height:720px; padding: 15px; border-radius: 5px; border: 1px solid #dee2e6; max-height: 100%; overflow-y: auto; line-height: 1.6;">${escapedContent}</div>`;
                      })
                     .catch(error => { /* ... 오류 표시 ... */
                          console.error('Error loading detail analysis:', error);
                          detailPanelTitle.textContent = `${nameForTitle} - 오류`;
                          detailPanelContent.innerHTML = `<p style="color: red;">상세 정보 로드 오류: ${error.message}</p>`;
                      });
                     // --- ▲▲▲ 상세 데이터 Fetch 시 헤더 추가 ▲▲▲ ---
                 }); // End click listener
            } // End else (storageKey exists)
            memberListBody.appendChild(clone);
        }); // End forEach
    } catch (error) {
         console.error(`Error loading complaints list (plaint.js):`, error);
         memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center; color: red;">목록 로드 오류: ${error.message}</td></tr>`;
     }
} // --- End of loadComplaints ---


// === DOM 로드 후 실행될 메인 로직 ===
document.addEventListener('DOMContentLoaded', () => {
    console.log("Plaint page specific DOMContentLoaded fired (plaint.js).");

    // Firebase 초기화 상태 확인
    isFirebaseInitialized_plaint = (typeof firebase !== 'undefined' && firebase.apps.length > 0);
    if (!isFirebaseInitialized_plaint) {
        console.warn("Firebase not initialized when DOMContentLoaded fired (plaint.js).");
        // Firebase 초기화는 app.js 등 다른 곳에서 수행된다고 가정
    }

    // --- DOM 요소 가져오기 ---
    const memberListBody = document.getElementById('member-list-body');
    const itemTemplate = document.getElementById('summary-row-template');
    const detailPanel = document.getElementById('detailPanel');
    const backdrop = document.getElementById('modalBackdrop');
    const panelCloseBtn = document.getElementById('panelCloseBtn'); // HTML ID 확인!
    const sidebarToggle = document.getElementById('sidebarToggle'); // 이 페이지에 있으면 사용
    const container = document.querySelector('.admin-container') || document.querySelector('.main-content-area'); // 페이지 레이아웃 클래스 확인

    // --- 필수 요소 확인 ---
    let essentialElementsFound = true;
    if (!memberListBody) { console.error("CRITICAL: #member-list-body not found!"); essentialElementsFound = false; }
    if (!itemTemplate || !itemTemplate.content) { console.error("CRITICAL: #summary-row-template not found!"); essentialElementsFound = false; }
    if (!detailPanel) { console.error("CRITICAL: #detailPanel not found!"); essentialElementsFound = false; }
    if (!backdrop) { console.error("CRITICAL: #modalBackdrop not found!"); essentialElementsFound = false; }
    if (!panelCloseBtn) { console.warn("Warning: #panelCloseBtn not found."); }

    if (!essentialElementsFound) {
        if (memberListBody) memberListBody.innerHTML = `<tr><td colspan="5">페이지 구성 오류.</td></tr>`; // Colspan 확인!
        return; // 중단
    }

    // --- 이벤트 리스너 설정 ---
    if (sidebarToggle && container) {
        sidebarToggle.addEventListener('click', () => container.classList.toggle('sidebar-collapsed'));
    }
    if (panelCloseBtn) { panelCloseBtn.addEventListener('click', closeDetailPanel); }
    if (backdrop) { backdrop.addEventListener('click', closeDetailPanel); }

    console.log("Plaint page event listeners set up. Waiting for Auth state...");
    // 초기 목록 로드는 Auth 상태 변경 리스너에서 수행하므로 여기서 호출 안 함

}); // === End DOMContentLoaded (plaint.js) ===


// === Firebase Auth 상태 변경 리스너 ===
// (이 코드는 app.js 또는 이 파일의 전역 스코프에 위치)
if (typeof firebase !== 'undefined') {
    firebase.auth().onAuthStateChanged(user => {
        console.log("[Plaint Auth] Auth State Changed. User:", user ? user.email : null);
        const memberListBody = document.getElementById('member-list-body'); // 이 페이지 식별

        if (memberListBody) { // plaint.html 에 해당 요소가 있을 때만 실행
            isFirebaseInitialized_plaint = true; // Auth 리스너 실행 => Firebase 초기화됨
            if (user) {
                 // 로그인 상태 -> 목록 로드
                 console.log("[Plaint Auth] User logged in on Plaint page. Calling loadComplaints().");
                 loadComplaints(); // <<< 로그인 확인 후 목록 로드
            } else {
                 // 로그아웃 상태
                 console.log("[Plaint Auth] User logged out on Plaint page.");
                 const columnCount = 5; // Colspan 확인!
                 memberListBody.innerHTML = `<tr><td colspan="${columnCount}" style="text-align: center;">목록을 보려면 로그인이 필요합니다.</td></tr>`;
                 currentUserToken_plaint = null; // 토큰 초기화
            }
        } else {
             // console.log("[Plaint Auth] Not on plaint page.");
        }
    });
} else {
    console.error("[Plaint Auth] Firebase object not found for Auth listener.");
}