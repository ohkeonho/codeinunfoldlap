// === Firebase 설정 ===
const firebaseConfig = {
    apiKey: "AIzaSyDVTDAzj0zMDqMMv8SO_qUOHuNOv6exCbU", // 실제 키 유지
    authDomain: "parkyoun-9971d.firebaseapp.com",
    projectId: "parkyoun-9971d",
    storageBucket: "parkyoun-9971d.firebasestorage.app",
    messagingSenderId: "1013836436406",
    appId: "1:1013836436406:web:a9cb2b5c44be85c263e717",
    measurementId: "G-EFG00C9DN1"
};

// === Firebase 앱 초기화 ===
firebase.initializeApp(firebaseConfig);
const auth = firebase.auth(); // Firebase Auth 객체 가져오기

console.log("app.js: 스크립트 로드 및 Firebase 초기화 완료.");

// === Helper Functions ===

// Firebase 에러 코드를 한국어 메시지로 변환하는 함수
function getErrorMessage(errorCode) {
    switch (errorCode) {
        case 'auth/user-not-found':
        case 'auth/invalid-credential':
            return '이메일 또는 비밀번호를 잘못 입력했습니다.';
        case 'auth/wrong-password':
            return '잘못된 비밀번호입니다.';
        case 'auth/invalid-email':
            return '유효하지 않은 이메일 형식입니다.';
        case 'auth/user-disabled':
            return '사용 중지된 계정입니다.';
        case 'auth/too-many-requests':
            return '로그인 시도 횟수가 너무 많습니다. 잠시 후 다시 시도해 주세요.';
        case 'auth/network-request-failed':
             return '네트워크 오류가 발생했습니다. 인터넷 연결 및 방화벽 설정을 확인해주세요.';
        default:
            console.error("알 수 없는 Firebase 에러 코드:", errorCode);
            return '로그인 중 오류가 발생했습니다. 다시 시도해 주세요.';
    }
}

// 로그인 폼 초기화 및 이벤트 리스너 설정 함수
function initializeLoginForm() {
    console.log("app.js: initializeLoginForm 함수 실행됨.");

    // HTML 요소 가져오기
    const loginForm = document.getElementById('login-form');
    const emailInput = document.getElementById('email');
    const passwordInput = document.getElementById('password');
    const messageDiv = document.getElementById('message');

    // 로그인 폼 관련 필수 요소 확인
    if (!loginForm || !emailInput || !passwordInput || !messageDiv) {
        console.error("app.js: 로그인 폼 관련 필수 HTML 요소 누락.");
        if (messageDiv) {
            messageDiv.textContent = "로그인 폼 로딩 오류.";
            messageDiv.style.color = 'red';
        }
        return;
    }
    console.log("app.js: login-form 요소 찾음. 이벤트 리스너 설정 시도.");

    // 로그인 폼 제출 리스너
    loginForm.onsubmit = (e) => {
        e.preventDefault();
        const email = emailInput.value;
        const password = passwordInput.value;
        console.log("app.js: 로그인 버튼 클릭됨. 이메일:", email);
        messageDiv.textContent = '로그인 시도 중...';
        messageDiv.style.color = 'inherit';

        // Firebase 이메일/비밀번호 로그인 시도
        auth.signInWithEmailAndPassword(email, password)
            .then((userCredential) => {
                // --- ▼▼▼ ID 토큰 방식: 로그인 성공 처리 (서버 호출 없음) ▼▼▼ ---
                console.log(`app.js: Firebase 로그인 성공 (${userCredential.user.email}).`);
                messageDiv.textContent = '로그인 성공! 메인 페이지로 이동합니다...';
                messageDiv.style.color = 'green';

                // ID 토큰 방식에서는 서버와 즉시 통신할 필요 없음.
                // 실제 API 요청 시점에 ID 토큰을 가져와서 사용함.

                // 로그인 성공 후 메인 페이지로 이동 (예: 0.5초 후)
                setTimeout(() => {
                     window.location.href = '/'; // 메인 페이지 경로
                }, 500);
                // --- ▲▲▲ ID 토큰 방식: 로그인 성공 처리 ▲▲▲ ---
            })
            .catch((error) => {
                // 로그인 실패 처리
                console.error('app.js: Firebase 로그인 실패:', error);
                // 여기서 auth/network-request-failed 오류가 계속 발생하면
                // Firebase 서버와의 통신 자체에 근본적인 문제가 있는 것임.
                const errorMessage = getErrorMessage(error.code || 'unknown');
                messageDiv.textContent = `로그인 실패: ${errorMessage}`;
                messageDiv.style.color = 'red';
            });
    }; // End of onsubmit handler
    console.log("app.js: 로그인 폼 이벤트 리스너 설정 완료 (onsubmit 사용).");
} // === End of initializeLoginForm ===


// === Firebase Auth 상태 변경 감지 리스너 ===
auth.onAuthStateChanged((user) => {
    console.log("app.js: onAuthStateChanged 콜백 실행됨. 현재 user 객체:", user ? user.email : 'null');
    if (user) {
        // 사용자가 Firebase에 로그인된 상태 (클라이언트 측)
        console.log(`app.js: 로그인된 사용자(${user.email}) 감지됨.`);

        // 로그인 페이지에 머물러 있다면 메인 페이지로 이동 (선택적)
        // (이전 디버깅 위해 주석 처리했던 것, 필요시 주석 해제)
        /*
        if (window.location.pathname.endsWith('login.html') || window.location.pathname.endsWith('/login')) {
            console.log("app.js: 로그인 페이지에서 사용자 감지. 메인('/')으로 이동 시도.");
            // window.location.href = '/';
        }
        */

    } else {
        // 사용자가 로그아웃 된 상태
        console.log("app.js: 로그아웃 상태 감지. 로그인 폼 초기화 함수 호출 시도.");
        if (document.getElementById('login-form')) {
             initializeLoginForm(); // 로그인 페이지라면 폼 초기화
        } else {
             console.log("app.js: 현재 페이지에 로그인 폼이 없으므로 initializeLoginForm 호출 안 함.");
             // 필요시 로그인 페이지로 이동시키는 로직 추가 가능
             // if (!window.location.pathname.includes('/login')) { window.location.href = '/login'; }
        }
    }
});
const logoutButton = document.querySelector('.logout'); // <<<--- 클래스 이름 사용

if (logoutButton) {
    console.log("app.js: 로그아웃 버튼 (.logout) 요소를 찾았습니다. 이벤트 리스너를 추가합니다.");
    logoutButton.addEventListener('click', () => {
        console.log('app.js: 로그아웃 버튼 클릭됨.');

        const currentUser = auth.currentUser; // 현재 로그인된 사용자 가져오기

        if (currentUser) {
            console.log(`app.js: 사용자 ${currentUser.email} 로그아웃 시도.`);

            // 1. (선택 사항) 백엔드에 리프레시 토큰 무효화 요청
            currentUser.getIdToken(true) // 최신 ID 토큰 강제 갱신
                .then((idToken) => {
                    console.log('app.js: 백엔드 /api/logout 호출하여 토큰 무효화 시도...');
                    return fetch('/api/logout', { // 백엔드 로그아웃 API 엔드포인트
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer ' + idToken
                        }
                    });
                })
                .then(response => {
                    if (!response.ok) {
                        // 백엔드 무효화 실패는 경고만 표시 (클라이언트 로그아웃은 계속 진행)
                        console.warn(`app.js: 백엔드 토큰 무효화 응답 실패 (Status: ${response.status}). 클라이언트 로그아웃은 계속합니다.`);
                    } else {
                        console.log('app.js: 백엔드 토큰 무효화 성공 또는 이미 무효 상태.');
                    }
                    // 2. Firebase 클라이언트 로그아웃 실행
                    return auth.signOut();
                })
                .then(() => {
                    // 3. 클라이언트 로그아웃 성공
                    console.log('app.js: Firebase 클라이언트 로그아웃 성공.');
                    alert('로그아웃 되었습니다.');
                    // 4. 로그인 페이지로 리디렉션
                    window.location.href = '/login'; // 실제 로그인 페이지 경로
                })
                .catch((error) => {
                    // 5. 로그아웃 과정 중 오류 발생
                    console.error('app.js: 로그아웃 처리 중 오류 발생:', error);
                    alert(`로그아웃 중 오류가 발생했습니다: ${error.message}`);
                    // 오류 발생 시에도 로그인 페이지로 이동 시도
                    window.location.href = '/login';
                });
        } else {
            // 이미 로그아웃된 상태에서 버튼을 누른 경우
            console.log('app.js: 사용자가 이미 로그아웃 상태입니다.');
            alert('이미 로그아웃 상태입니다.');
            window.location.href = '/login'; // 로그인 페이지로 이동
        }
    });
} else {
    // 페이지에 로그아웃 버튼이 없을 수 있으므로 경고만 표시
    console.warn("app.js: 클래스가 'logout'인 요소를 찾을 수 없습니다.");
}
// --- ▲▲▲ 로그아웃 버튼 처리 로직 추가 ▲▲▲ ---


// === 페이지 로드 시 로그인 폼 초기화 (로그인 페이지인 경우) ===
// onAuthStateChanged 리스너가 처리하므로 이 부분은 없어도 될 수 있음.
// 만약 로그인 페이지에서만 이 app.js를 로드한다면 유지 가능.
if (document.getElementById('login-form')) {
    // 페이지 로드 시점에 로그아웃 상태라면 바로 초기화 함수 호출
    if (!auth.currentUser) {
         initializeLoginForm();
    }
} else {
     console.log("app.js: 현재 페이지에 로그인 폼(#login-form)이 없습니다.");
}