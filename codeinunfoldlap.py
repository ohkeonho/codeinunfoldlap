# codeinunfoldlap.py

# --- 기본 및 Flask 관련 임포트 ---
from flask import Flask, render_template # request, jsonify 등은 API 라우트에서 사용
from flask_cors import CORS
import os
import firebase_admin
from firebase_admin import credentials, auth

# --- 설정 파일에서 Firebase 설정 가져오기 ---
try:
    # config.py 파일이 같은 디렉토리에 있어야 함
    from config import FIREBASE_CRED_PATH
except ImportError:
    print("🚨 CRITICAL ERROR: config.py 에서 FIREBASE_CRED_PATH를 import할 수 없습니다!")
    # 기본 경로를 사용하거나 오류를 발생시켜 앱 중지
    FIREBASE_CRED_PATH = 'parkyoun-9971d-firebase-adminsdk-fbsvc-a5c658338f.json'

# --- Firebase Admin SDK 초기화 ---
# 앱 시작 시 한 번만 실행되어야 함
try:
    if not os.path.exists(FIREBASE_CRED_PATH):
        raise FileNotFoundError(f"Firebase Admin SDK 키 파일 없음: {FIREBASE_CRED_PATH}")
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
        print("✅ [App] Firebase Admin SDK 초기화 성공")
    else:
        print("ℹ️ [App] Firebase Admin SDK 이미 초기화됨.")
except Exception as e:
    print(f"🚨 [App] Firebase Admin SDK 초기화 실패: {e}")
    # 심각한 오류 처리 필요

# --- Flask 앱 생성 및 기본 설정 ---
print("--- [App] Flask 앱 생성 ---")
app = Flask(__name__)
CORS(app)
# 파일 크기 제한은 여기서 설정
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
print(f"--- [App] MAX_CONTENT_LENGTH 설정: {app.config['MAX_CONTENT_LENGTH']} bytes ---")

# --- 설정 변수, 저장소, 클래스, 헬퍼 함수 정의는 모두 삭제됨 ---
# (각각 config.py, storage.py, clients.py, utils.py 로 이동됨)

# --- 비-API 라우트 정의 ---
print("--- [App] 비-API 라우트 정의 중... ---")
@app.route('/')
def index_page():
    return render_template('login.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/main')
def main_page():
    # TODO: 로그인 여부 확인 후 main.html 또는 login.html 로 리디렉션 고려
    return render_template('index.html')

@app.route('/admin')
def admin_page():
    # TODO: 관리자 인증 로직 추가 필요
    return render_template('admin.html')

@app.route('/plaint')
def plaint_page():
    # TODO: 인증 로직 추가 필요
    return render_template('plaint.html')

@app.route('/supplementaries')
def supplementary_page():
     # TODO: 인증 로직 추가 필요
    return render_template('supplementary.html')

@app.route('/prosecutor')
def prosecutor_page():
     # TODO: 인증 로직 추가 필요
    return render_template('prosecutor.html')

@app.route('/agreements')
def agreements_page():
     # TODO: 인증 로직 추가 필요
    return render_template('agreement.html')
print("--- [App] 비-API 라우트 정의 완료 ---")

# --- API Blueprint 등록 ---
print("--- [App] API Blueprint 등록 시도... ---")
try:
    # api/routes.py 에서 정의된 api_bp 를 가져옴
    from api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    print("✅ [App] API Blueprint 등록 완료 (prefix: /api).")
except ImportError as e_imp:
    # 이 오류는 이제 발생하지 않아야 함
    print(f"🚨 [App] CRITICAL ERROR: API Blueprint 임포트 실패 ({e_imp}). API 사용 불가.")
except Exception as e_reg:
     print(f"🚨 [App] CRITICAL ERROR: API Blueprint 등록 오류 ({e_reg}). API 사용 불가.")

# --- 앱 실행 ---
if __name__ == '__main__':
    print("🚀 Flask 서버 시작 중...")
    # 개발 시 debug=True 로 설정하여 자동 리로드 및 상세 오류 확인
    app.run(host='0.0.0.0', port=8000, debug=False) # <<< debug=True 로 변경!