# config.py
import os
import google.generativeai as genai

# --- 라이브러리 로드 및 상태 ---
# Vision
try:
    from google.cloud import vision
    from google.api_core import exceptions as google_exceptions
    # 환경 변수 또는 직접 경로 지정 (환경 변수 이름 구분 권장)
    GOOGLE_API_KEY_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_VISION', 'notional-buffer-445706-e0-b736090bdc8a.json')
    VISION_AVAILABLE = True
    print("✅ [Config] google-cloud-vision 로드됨.")
    if not os.path.exists(GOOGLE_API_KEY_PATH):
        print(f"🚨 [Config] WARNING: Google Cloud Vision API 키 파일 없음: {GOOGLE_API_KEY_PATH}")
        # VISION_AVAILABLE = False # 필요시 기능 비활성화
except ImportError:
    vision = None
    google_exceptions = None
    GOOGLE_API_KEY_PATH = None
    VISION_AVAILABLE = False
    print("🚨 [Config] WARNING: google-cloud-vision 미설치.")

# PyPDF2
try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
    print("✅ [Config] PyPDF2 로드됨.")
except ImportError:
    PYPDF2_AVAILABLE = False
    print("⚠️ [Config] 경고: PyPDF2 미설치.")
    class PdfReader: # NameError 방지용 Mock 클래스
        def __init__(self, stream): pass
        @property
        def pages(self): return []
        @property
        def is_encrypted(self): return False
        def decrypt(self, pwd): return 1

# pydub
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
    print("✅ [Config] pydub 로드됨.")
except ImportError:
    PYDUB_AVAILABLE = False
    print("🚨 [Config] WARNING: pydub 미설치. ffmpeg 필요.")
    class AudioSegment: # NameError 방지용 Mock 클래스
        @staticmethod
        def from_file(file, format):
            raise ImportError("pydub is not available, cannot process audio")
        def export(self, out_f, format):
            raise ImportError("pydub is not available, cannot process audio")

# --- API 설정 ---
# Clova
invoke_url = 'https://clovaspeech-gw.ncloud.com/external/v1/10943/01c19849854a8e51219a3e63a98d4a4565d71c73ee7566fdf84957a80c1897be'
secret = '63d30b73e68b4defa3dc1815153985ba'

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyBF0F6T4t-Y-h0v6-RJJ8f9pe01B8c_6Og") # 환경 변수 또는 기본값
gemini_model = None
if not GEMINI_API_KEY:
    print("🚨 [Config] 경고: GEMINI_API_KEY 미설정.")
else:
    try:
        print("✅ [Config] Gemini API 설정 시도 중...")
        genai.configure(api_key=GEMINI_API_KEY)
        # 사용 모델 확인 및 필요시 변경 ('gemini-1.5-flash-latest' 등)
        gemini_model = genai.GenerativeModel('gemini-2.5-flash-preview-04-17')
        print(f"✅ [Config] Gemini API 설정 완료. 모델: {getattr(gemini_model, 'model_name', 'N/A')}")
    except Exception as e:
        print(f"🚨 [Config] Gemini API 설정 오류: {e}")
        gemini_model = None

# --- Firebase ---
FIREBASE_CRED_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS_FIREBASE', 'parkyoun-9971d-firebase-adminsdk-fbsvc-a5c658338f.json')

# --- 기타 설정 ---
ADMIN_EMAILS = ['admin@example.com'] # 실제 관리자 이메일 목록으로 교체

# --- Flask App Config (메인 파일에서 사용) ---
# 파일 크기 제한은 보통 Flask 앱 설정에 직접 넣는 것이 일반적임
# MAX_FILE_SIZE = 50 * 1024 * 1024 # 필요하다면 여기서 정의하고 메인 파일에서 import