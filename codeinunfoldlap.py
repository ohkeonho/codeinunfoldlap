from flask import Flask, request, jsonify, send_from_directory, abort,render_template, send_from_directory,make_response # make_response
import os
import requests
import json
from flask_cors import CORS
from pydub import AudioSegment
from datetime import date,datetime ,timezone
import traceback
import google.generativeai as genai
import re
import firebase_admin                 # <--- 이 줄을 추가하세요!
from firebase_admin import credentials, auth
from flask import Flask, request, jsonify
from werkzeug.datastructures import FileStorage
import tempfile
from werkzeug.utils import secure_filename 
try:
    from google.cloud import vision
    from google.api_core import exceptions as google_exceptions # Google API 오류 처리
    # --- 중요: Google Cloud API 키 파일 경로 설정 ---
    # 아래 'path/to/your/keyfile.json' 부분을 실제 키 파일 경로로 변경하거나
    # GOOGLE_APPLICATION_CREDENTIALS 환경 변수를 설정해야 합니다.
    # 예시: GOOGLE_API_KEY_PATH = r"C:\Users\user\keys\my-google-cloud-key.json"
    GOOGLE_API_KEY_PATH = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'notional-buffer-445706-e0-b736090bdc8a.json') # <<< 실제 키 파일 경로로 꼭 수정하세요!!!
    # ---------------------------------------------
    VISION_AVAILABLE = True # 라이브러리 로드 성공 시 True
    print("✅ google-cloud-vision 라이브러리 로드됨.")
    # API 키 파일 존재 여부 미리 확인 (선택적)
    if not os.path.exists(GOOGLE_API_KEY_PATH):
         print(f"🚨 WARNING: Google Cloud API 키 파일을 찾을 수 없습니다: {GOOGLE_API_KEY_PATH}")
         print(f"🚨 -> 경로가 올바르지 않으면 이미지 OCR 기능이 작동하지 않습니다.")
         # 필요하다면 키 파일 없을 때 VISION_AVAILABLE = False 로 설정 가능
except ImportError:
    vision = None # 임시 정의 (NameError 방지용)
    google_exceptions = None # 임시 정의
    GOOGLE_API_KEY_PATH = None
    VISION_AVAILABLE = False # 라이브러리 로드 실패 시 False
    print("🚨 WARNING: google-cloud-vision 라이브러리가 설치되지 않았습니다. 이미지 OCR 처리를 할 수 없습니다.")
    print("🚨 -> 해결 방법: 터미널에서 'pip install google-cloud-vision' 실행 및 Google Cloud 인증 설정을 완료하세요.")
try:
    # pypdf 는 PyPDF2의 개선된 최신 버전입니다. 가능하면 pypdf를 사용하세요.
    # 설치: pip install pypdf
    from pypdf import PdfReader
    # 만약 구 버전 PyPDF2를 꼭 사용해야 한다면 아래 주석 해제하고 위 라인 주석 처리
    # 설치: pip install pypdf2
    # from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True # <<< 변수 정의
    print("✅ PDF 처리 라이브러리 (pypdf/PyPDF2) 로드됨.")
except ImportError:
    PYPDF2_AVAILABLE = False # <<< 변수 정의
    print("⚠️ 경고: PDF 처리 라이브러리(pypdf 또는 PyPDF2)를 찾을 수 없습니다. PDF 텍스트 추출이 비활성화됩니다.")
    # PdfReader가 정의되지 않아 이후 코드에서 NameError 발생 방지 (선택적)
    class PdfReader: pass # 임시 클래스 정의
try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True # pydub 임포트 성공 시 True로 설정
    print("✅ pydub 라이브러리 로드됨.")
except ImportError:
    PYDUB_AVAILABLE = False # pydub 임포트 실패 시 False로 설정
    print("🚨 WARNING: pydub 라이브러리가 설치되지 않았습니다. /record 경로 사용 시 오류가 발생할 수 있습니다.")
    print("🚨 -> 해결 방법: 터미널에서 'pip install pydub' 실행 및 ffmpeg 설치 확인")
    # pydub을 찾을 수 없을 때 AudioSegment를 임시 정의하여 다른 곳에서 NameError 방지
    class AudioSegment:
        @staticmethod
        def from_file(file, format): pass
        def export(self, out_f, format): pass
try:
    # 서비스 계정 키 파일 경로 (실제 경로로 변경!)
    cred_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', 'parkyoun-9971d-firebase-adminsdk-fbsvc-a5c658338f.json') # <<< 실제 키 파일 경로!
    if not os.path.exists(cred_path):
        raise FileNotFoundError(f"Firebase Admin SDK 키 파일을 찾을 수 없습니다: {cred_path}")
    cred = credentials.Certificate(cred_path)
    # 앱 이름 중복 방지 (이미 초기화되었다면 건너뛰기)
    if not firebase_admin._apps:
         firebase_admin.initialize_app(cred)
         print("✅ Firebase Admin SDK 초기화 성공")
    else:
         print("ℹ️ Firebase Admin SDK 이미 초기화됨.")
except Exception as e:
    print(f"🚨 Firebase Admin SDK 초기화 실패: {e}")
# --- Google Cloud API 키 파일 경로 ---
# !!! 중요: 실제 서비스 계정 키 JSON 파일의 전체 경로로 변경해주세요 !!!
# 예: GOOGLE_API_KEY_PATH = "C:/Users/YourUser/Downloads/notional-buffer-445706-e0-b736090bdc8a.json"
# 예: GOOGLE_API_KEY_PATH = "/home/youruser/keys/notional-buffer-445706-e0-b736090bdc8a.json"
app = Flask(__name__)
CORS(app)

# --- 설정 (Clova, Gemini) ---
invoke_url = 'https://clovaspeech-gw.ncloud.com/external/v1/10943/01c19849854a8e51219a3e63a98d4a4565d71c73ee7566fdf84957a80c1897be'
secret = '63d30b73e68b4defa3dc1815153985ba'

# --- ✨ Gemini API 설정 수정 ✨ ---
try:
    # 실제 운영 환경에서는 환경 변수 사용을 강력히 권장합니다.
    # 예: GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    # 제공된 API 키를 직접 사용합니다. (테스트 목적)
    GEMINI_API_KEY = "AIzaSyBF0F6T4t-Y-h0v6-RJJ8f9pe01B8c_6Og"

    # API 키 변수가 비어있는지만 확인합니다.
    if not GEMINI_API_KEY:
        print("🚨 경고: GEMINI_API_KEY 가 설정되지 않았습니다. Gemini 요약 기능이 작동하지 않습니다.")
        gemini_model = None
    else:
        # API 키가 존재하면 설정을 시도합니다.
        print("✅ Gemini API 키를 사용하여 설정 시도 중...")
        genai.configure(api_key=GEMINI_API_KEY)
        # 사용할 모델 설정 (예: gemini-1.5-flash-latest)
        gemini_model = genai.GenerativeModel('gemini-2.0-flash')
        # 모델 이름 확인을 위한 로그 추가 (선택 사항)
        # print(f"✅ Gemini API 설정 완료. 사용 모델: {gemini_model.model_name}")
        print("✅ Gemini API 설정 완료.")

except Exception as e:
    print(f"🚨 Gemini API 설정 중 오류 발생: {e}")
    # API 키 관련 흔한 오류 메시지 확인 및 안내
    error_str = str(e).lower()
    if "api key not valid" in error_str or "permission denied" in error_str or "authenticate" in error_str:
         print("   👉 오류 상세: 제공된 API 키가 유효하지 않거나 필요한 권한이 없을 수 있습니다. 키를 확인해주세요.")
    elif "quota" in error_str:
         print("   👉 오류 상세: API 할당량을 초과했을 수 있습니다.")
    gemini_model = None # 오류 발생 시 None으로 설정

# --- ClovaSpeechClient 클래스 ---
class ClovaSpeechClient:
    def req_upload(self, file, completion, callback=None, userdata=None, forbiddens=None, boostings=None,
                   wordAlignment=True, fullText=True, diarization=True, sed=None):
        """
        Clova Speech API에 음성 파일을 업로드하고 인식을 요청합니다.
        파일 경로(str) 또는 Flask의 FileStorage 객체를 처리할 수 있습니다.

        :param file: 파일 경로(str) 또는 FileStorage 객체.
        :param completion: 'sync' 또는 'async'.
        :param ...: 기타 Clova API 파라미터.
        :return: requests.Response 객체.
        """
        request_body = {
            "language": "ko-KR",
            "completion": completion,
            "wordAlignment": wordAlignment,
            "fullText": fullText,
            # diarization 파라미터 구조에 주의: 'enable' 키 필요
            "diarization": {"enable": diarization, "speakerCountMin": 2, "speakerCountMax": 2} # 필요시 speakerCount 조절
        }
        # print("=== [보내는 Clova JSON params] ===") # 필요시 주석 해제
        # print(json.dumps(request_body, ensure_ascii=False, indent=2))

        # --- 선택적 파라미터 추가 ---
        if callback is not None: request_body['callback'] = callback
        if userdata is not None: request_body['userdata'] = userdata
        if forbiddens is not None: request_body['forbiddens'] = forbiddens
        if boostings is not None: request_body['boostings'] = boostings
        if sed is not None: request_body['sed'] = sed

        headers = {
            'Accept': 'application/json;UTF-8',
            'X-CLOVASPEECH-API-KEY': secret
        }

        # --- 'file' 파라미터 타입에 따라 'media' 데이터 준비 ---
        media_data_to_send = None
        file_to_close = None # 직접 열었던 파일을 닫기 위해

        try:
            if isinstance(file, str):
                # 타입 1: 파일 경로(문자열)인 경우 -> 파일을 직접 열기
                print(f"DEBUG [ClovaClient]: 파일 경로에서 열기 시도: {file}")
                # 파일을 열어서 requests에 전달, 나중에 닫아주어야 함
                file_to_close = open(file, 'rb')
                media_data_to_send = file_to_close
            elif isinstance(file, FileStorage):
                # 타입 2: FileStorage 객체인 경우 -> 필요한 정보 추출
                print(f"DEBUG [ClovaClient]: FileStorage 객체 사용: {file.filename}")
                # requests는 (파일명, 파일스트림, 컨텐츠타입) 튜플을 잘 처리함
                media_data_to_send = (file.filename, file.stream, file.content_type)
            # 필요한 경우 다른 타입 처리 추가 (예: io.BytesIO)
            # elif isinstance(file, io.BytesIO):
            #     print(f"DEBUG [ClovaClient]: BytesIO 객체 사용")
            #     # BytesIO는 파일명이 없으므로, 임의의 파일명 지정 또는 전달 필요
            #     filename = getattr(file, 'name', 'bytes_audio.bin') # name 속성이 있다면 사용
            #     media_data_to_send = (filename, file, 'application/octet-stream') # 컨텐츠 타입 추정
            else:
                # 지원하지 않는 타입 처리
                raise TypeError(f"지원하지 않는 파일 타입입니다: {type(file)}")

            # --- requests 라이브러리에 전달할 files 딕셔너리 구성 ---
            files = {
                'media': media_data_to_send,
                # 'params'는 파일이 아니라 JSON 데이터를 보내므로 튜플 형태로 구성
                'params': (None, json.dumps(request_body, ensure_ascii=False), 'application/json')
            }

            # --- API 요청 실행 ---
            print(f"DEBUG [ClovaClient]: requests.post 호출 시작 (URL: {invoke_url + '/recognizer/upload'})")
            response = requests.post(headers=headers, url=invoke_url + '/recognizer/upload', files=files)
            print(f"DEBUG [ClovaClient]: requests.post 호출 완료 (Status: {response.status_code})")

        except Exception as e:
             print(f"🚨 ERROR [ClovaClient]: API 요청 중 오류 발생: {e}")
             # 오류 발생 시에도 파일 닫기 시도
             raise e # 오류를 다시 발생시켜 상위에서 처리하도록 함
        finally:
            # --- 파일을 직접 열었다면 반드시 닫아주기 ---
            if file_to_close is not None:
                try:
                    print(f"DEBUG [ClovaClient]: 직접 열었던 파일 닫기: {getattr(file_to_close, 'name', 'N/A')}")
                    file_to_close.close()
                except Exception as e_close:
                    print(f"🚨 WARNING [ClovaClient]: 파일 닫기 중 오류: {e_close}")

        return response



# --- Helper function to extract text from PDF ---
def summarize_with_context(transcribed_text, all_document_text_parts, key_topic, previous_summary_text):
    # transcribed_text,
    """ 관리자 업로드 상세 분석용 함수 """
    if not gemini_model: return "Gemini API 미설정"
    if not hasattr(gemini_model, 'generate_content'): return "Gemini 모델 초기화 오류"
    if not transcribed_text and not all_document_text_parts and not previous_summary_text: return "분석할 내용(녹취록, PDF, 이전 요약)이 전혀 없습니다."
    if(key_topic == "고소장"):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
    elif(key_topic == "보충이유서"):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
        # 
    elif(key_topic == "검찰의견서"):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
       

        """
    # --- End of Prompt ---

    # --- Outer Try-Except block for API call ---
    try:
        print(f"⏳ --- Gemini에게 '{key_topic}', PDF, 이전 요약 기반 최종 분석 요청 (Admin) ---")
        response = gemini_model.generate_content(prompt)
        print("✅ --- Gemini 응답 받음 ---")

        # --- Text Extraction Logic ---
        summary_text = None
        if response:
            # --- Inner Try-Except for extraction from response object ---
            try:
                # 1. Check direct .text attribute
                if hasattr(response, 'text') and response.text:
                     summary_text = response.text
                     print("  - Text found directly in response.text")
                # 2. Check .candidates if no direct .text
                elif response.candidates:
                    print("  - Checking response.candidates for text...")
                    for candidate in response.candidates:
                        if candidate.content and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'text'):
                                    summary_text = part.text
                                    print(f"  - Text found in candidate part: '{summary_text[:50]}...'")
                                    break # Use first text part
                        if summary_text: break # Stop checking candidates
                # else: # Optional debug log
                #    print("  - Response object exists but has no .text or .candidates")

            except AttributeError as ae:
                 print(f"🚨 Gemini 응답 객체 속성 접근 오류: {ae}")
                 print(f"   Response object structure might be different: {response}")
                 summary_text = None # Ensure None on error
            except Exception as e:
                print(f"🚨 응답 텍스트 추출 중 예상치 못한 오류: {e}")
                summary_text = None # Ensure None on error
            # --- End of Inner Try-Except ---

        # --- Return based on extraction ---
        if summary_text:
            return summary_text # <<< SUCCESSFUL RETURN
        else:
            print(f"⚠️ Gemini 내용 없음 또는 텍스트 추출 불가. 응답 객체: {response}")
            return "Gemini 분석 생성 중 응답 처리 오류 발생 (내용 없음 또는 추출 불가)." # <<< RETURN on extraction failure

    # --- Outer Except block (Handles API call errors) ---
    # ✨ 이 except 블록이 위의 try와 같은 들여쓰기 레벨인지 확인! ✨
    except Exception as e:
        print(f"🚨 Gemini API 호출 중 오류 발생 (Admin - '{key_topic}'): {e}")
        print(traceback.format_exc())
        error_message = f"Gemini 분석 생성 중 오류 발생: {type(e).__name__}"
        # (오류 메시지 상세화 로직 - 이전 코드 참고)
        error_str = str(e).lower();
        if "api key" in error_str or "permission denied" in error_str: error_message += " (API 키/권한 문제)"
        elif "quota" in error_str: error_message += " (API 할당량 초과)"
        elif " deadline exceeded" in error_str: error_message += " (요청 시간 초과)"
        elif "resource exhausted" in error_str: error_message += " (리소스 부족)"
        elif "model not found" in error_str: error_message += " (모델 이름 확인 필요)"
        elif "safety" in error_str: error_message += " (콘텐츠 안전 문제로 차단됨)"
        # ... 기타 특정 오류 확인 추가 가능 ...
        return error_message # <<< RETURN on API call failure



# --- summarize_text_with_gemini 함수 ---
def summarize_text_with_gemini(text_to_summarize):
    # ✨ gemini_model 객체 유효성 검사 강화 ✨
    if not gemini_model:
        print("ℹ️ Gemini API가 설정되지 않아 요약을 건너뜁니다.")
        return "Gemini API가 설정되지 않았거나 초기화에 실패하여 요약을 생성할 수 없습니다."
    # 모델 객체에 generate_content 메서드가 있는지 확인 (더 안전)
    if not hasattr(gemini_model, 'generate_content'):
         print("🚨 오류: Gemini 모델 객체가 유효하지 않습니다 (generate_content 없음).")
         return "Gemini 모델 초기화 오류로 요약 생성 불가."

    if not text_to_summarize:
        return "요약할 텍스트가 없습니다."

    prompt = f"""내용정리하고 법률분석 해줘
{text_to_summarize}"""
    try:
        print("⏳ --- Gemini에게 요약 요청 ---")
        response = gemini_model.generate_content(prompt)
        print("✅ --- Gemini 응답 받음 ---")

        # 응답 구조 확인 및 텍스트 추출 (다양한 구조 가능성 고려)
        summary_text = None
        if response:
             if hasattr(response, 'text') and response.text:
                 summary_text = response.text
             elif response.candidates and len(response.candidates) > 0:
                 candidate = response.candidates[0]
                 if candidate.content and candidate.content.parts and len(candidate.content.parts) > 0:
                     summary_text = candidate.content.parts[0].text

        if summary_text:
            return summary_text
        else:
            # 응답은 받았으나 텍스트 추출 실패 시
            print(f"⚠️ Gemini로부터 예상치 못한 응답 형식 또는 빈 내용 받음: {response}")
            return "Gemini 요약 생성 중 응답 처리 오류 발생 (내용 없음)."

    except Exception as e:
        print(f"🚨 Gemini API 호출 중 오류 발생: {e}")
        print(traceback.format_exc()) # 개발 중 상세 오류 확인에 유용
        error_message = f"Gemini 요약 생성 중 오류 발생: {type(e).__name__}"
        error_str = str(e).lower()
        if "api key" in error_str or "permission denied" in error_str or "authenticate" in error_str:
             error_message += " (API 키 인증/권한 문제 가능성 높음)"
        elif "quota" in error_str:
             error_message += " (API 할당량 초과 가능성 높음)"
        elif "model not found" in error_str:
             error_message += " (요청한 모델 이름을 찾을 수 없음)"
        elif "deadline exceeded" in error_str or "timeout" in error_str:
             error_message += " (요청 시간 초과)"
        elif "resource exhausted" in error_str:
             error_message += " (리소스 부족, 서버 부하 가능성)"

        return error_message
    


# --- 파일 이름 및 경로 관련 함수 ---
def sanitize_filename(filename):
    # 파일 이름에서 경로 구분자 및 위험 문자 제거/변경
    # os.path.basename 추가하여 경로 부분 제거 후 처리
    base_name = os.path.basename(filename)
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", base_name)
    # 추가적으로 앞뒤 공백 제거 등 필요시 처리
    return sanitized.strip()

def get_unique_filename(directory, base_filename, extension):
    # 디렉토리가 없으면 생성 (오류 처리 포함)
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
            print(f"✅ 디렉토리 생성됨: {directory}")
        except OSError as e:
            print(f"🚨 디렉토리 생성 실패: {e}. 파일 저장 경로: {directory}")
            # 디렉토리 생성 실패 시 처리가 필요할 수 있음 (예: 기본 경로 사용, 예외 발생)
            # 여기서는 일단 진행하되, 파일 저장 시 오류 발생 가능성 있음

    counter = 1
    # 확장자가 '.'으로 시작하지 않으면 추가
    if not extension.startswith('.'):
        extension = '.' + extension

    file_path = os.path.join(directory, f"{base_filename}{extension}")
    while os.path.exists(file_path):
        file_path = os.path.join(directory, f"{base_filename}_{str(counter).zfill(2)}{extension}")
        counter += 1
    return file_path

# --- Helper function to extract text from PDF ---
def extract_text_from_file(original_filename, file_path=None, file_bytes=None):
    """
    주어진 파일 경로 또는 바이트 내용에서 텍스트를 추출합니다.
    (PyPDF2, Vision 사용 예시)
    """
    print(f"📄 텍스트 추출 시작: {original_filename} (경로: {file_path}, 바이트 제공 여부: {file_bytes is not None})")

    # --- 입력 유효성 검사 ---
    if not file_path and not file_bytes:
        return "오류: 파일 경로 또는 파일 내용(bytes)이 제공되지 않았습니다."
    if not original_filename:
         return "오류: 원본 파일명이 제공되지 않았습니다."

    try:
        _, file_extension = os.path.splitext(original_filename)
        file_extension = file_extension.lower()
    except Exception as e:
        return f"오류: 파일 확장자 확인 불가 - {e}"

    # --- 파일 내용 접근 (경로 우선) ---
    content_to_process = None
    if file_path and os.path.exists(file_path):
         # Vision API는 파일 경로 직접 지원 안 함 -> 필요 시 여기서 읽거나,
         # PDF 처럼 라이브러리가 경로를 지원하면 그대로 사용
         # 여기서는 Vision API를 위해 bytes로 읽는 예시 포함
         try:
             with open(file_path, 'rb') as f:
                 content_to_process = f.read()
             print(f"   - 파일 경로에서 내용 읽기 완료: {file_path} ({len(content_to_process)} bytes)")
         except Exception as read_err:
             return f"오류: 파일 읽기 실패 ({file_path}): {read_err}"
    elif file_bytes:
         content_to_process = file_bytes
         print(f"   - 제공된 바이트 내용 사용 ({len(content_to_process)} bytes)")
    else:
        return f"오류: 유효한 파일 경로 또는 내용 없음 ({original_filename})."

    # --- 확장자별 처리 ---
    # PDF 처리
    if file_extension == '.pdf':
        if not PYPDF2_AVAILABLE: return "오류: PDF 처리 라이브러리 로드 실패."
        text = ""
        try:
            # BytesIO를 사용하여 메모리 내에서 처리
            pdf_file_in_memory = io.BytesIO(content_to_process)
            reader = PdfReader(pdf_file_in_memory)
            if reader.is_encrypted:
                try:
                     if reader.decrypt('') == 0: return f"오류: 암호화된 PDF ({original_filename})."
                except Exception as decrypt_err: return f"오류: PDF 복호화 오류 ({original_filename}): {decrypt_err}"
            for page in reader.pages:
                try: text += (page.extract_text() or "") + "\n"
                except Exception as page_err: text += f"[페이지 추출 오류: {page_err}]\n"
            extracted_text = text.strip()
            print(f"   - PDF 텍스트 추출 완료 ({original_filename})")
            return extracted_text if extracted_text else "PDF에서 텍스트를 추출할 수 없었습니다."
        except Exception as e: return f"오류: PDF 처리 중 예외 ({original_filename}): {e}"

    # 이미지 처리 (Google Cloud Vision)
    elif file_extension in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp', '.ico']:
        if not VISION_AVAILABLE: return "오류: Vision 라이브러리 로드 실패."
        if not GOOGLE_API_KEY_PATH or not os.path.exists(GOOGLE_API_KEY_PATH): return f"오류: Google API 키 파일 문제."
        try:
            print(f"   - Google Vision API 호출 시작 ({original_filename})")
            client = vision.ImageAnnotatorClient.from_service_account_file(GOOGLE_API_KEY_PATH)
            image = vision.Image(content=content_to_process) # 바이트 내용 사용
            response = client.document_text_detection(image=image)
            if response.error.message: return f"오류: Vision API - {response.error.message}"
            extracted_text = response.full_text_annotation.text.strip()
            print(f"   - Vision API 텍스트 추출 완료 ({original_filename})")
            return extracted_text if extracted_text else "이미지에서 텍스트를 추출할 수 없었습니다."
        except Exception as e: return f"오류: 이미지 처리 중 예외 ({original_filename}): {e}"

    # 지원하지 않는 형식
    else: return f"오류: 지원하지 않는 파일 형식 ({file_extension})."


@app.route("/api/logout", methods=['POST'])
def logout_user():
    """
    사용자 로그아웃 처리 (Firebase 리프레시 토큰 무효화).
    성공/실패 여부를 JSON으로 반환합니다.
    프론트엔드에서 로그아웃 버튼 클릭 시 호출합니다.
    """
    uploader_uid = None
    try:
        # 1. 요청 헤더에서 ID 토큰 가져오기
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/logout: 인증 토큰 없음.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]

        # 2. ID 토큰 검증하여 UID 얻기
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid']
            print(f"ℹ️ /api/logout 요청 사용자 UID: {uploader_uid}")
        except Exception as auth_err:
            # 토큰이 유효하지 않으면 무효화할 필요 없음 (이미 로그아웃 상태 간주 가능)
            print(f"⚠️ /api/logout: 토큰 검증 실패 (이미 로그아웃 상태일 수 있음): {auth_err}")
            # 여기서 401을 반환해도 되고, 성공(200 OK)으로 간주하고 클라이언트에서 signOut하게 할 수도 있음
            # 여기서는 일단 성공으로 간주하여 클라이언트 signOut을 유도
            return jsonify({"message": "토큰 검증 실패, 클라이언트에서 로그아웃 진행"}), 200

        # 3. 리프레시 토큰 무효화 (UID 사용)
        try:
            auth.revoke_refresh_tokens(uploader_uid)
            print(f"✅ UID {uploader_uid} 의 리프레시 토큰 무효화 성공.")
            return jsonify({"message": "성공적으로 로그아웃 처리되었습니다 (토큰 무효화)."}), 200
        except Exception as revoke_err:
            print(f"🚨 /api/logout: 리프레시 토큰 무효화 실패 (UID: {uploader_uid}): {revoke_err}")
            traceback.print_exc()
            # 무효화 실패 시에도 클라이언트에서는 로그아웃 처리를 할 수 있도록
            # 오류를 반환하되 심각한 서버 오류(500)보다는 클라이언트 오류(400)나 성공(200)으로 처리할 수도 있음
            return jsonify({"error": "로그아웃 처리 중 서버 오류 (토큰 무효화 실패)", "detail": str(revoke_err)}), 500

    except Exception as e:
        # 예상치 못한 오류 처리
        print(f"🚨 /api/logout: 예외 발생: {e}")
        traceback.print_exc()
        return jsonify({"error": "로그아웃 처리 중 예기치 않은 오류 발생"}), 500
# --- ▲▲▲ 로그아웃 API 엔드포인트 추가 ▲▲▲ ---


def find_previous_summary_content(name, phone, region):
    """
    모든 관련 저장소에서 이름/전화번호/지역이 일치하는 가장 최신의 요약 내용을 찾습니다.
    """
    print(f"⏳ 이전 요약 검색 시도 (모든 저장소): name={name}, phone={phone}, region={region}")
    
    found_summaries = [] # 찾은 요약 정보들을 저장할 리스트 (타임스탬프 포함)

    # 검색 대상 저장소 목록 (필요에 따라 추가/제거)
    storages_to_search = {
        "User": user_memory_storage,             # 사용자 직접 업로드/녹음 (중첩 구조)
        "Complaint": complaint_storage,         # 고소장 (단일 구조)
        "Supplementary": supplementary_storage,   # 보충이유서 (단일 구조)
        "ProsecutorOpinion": prosecutor_opinion_storage, # 검찰의견서 (단일 구조)
        "Admin": admin_memory_storage           # 기타 관리자 업로드 (단일 구조)
    }

    for storage_name, storage_dict in storages_to_search.items():
        if storage_name == "User": # User 저장소는 중첩 구조이므로 별도 처리
            for user_id, user_data in storage_dict.items():
                for storage_key, data_item in user_data.items():
                    metadata = data_item.get('metadata', {})
                    if metadata.get('name') == name and metadata.get('phone') == phone and metadata.get('region') == region:
                        timestamp_iso = data_item.get('timestamp')
                        summary = data_item.get('summary')
                        if timestamp_iso and summary: # 타임스탬프와 요약이 모두 있어야 유효
                            found_summaries.append({'timestamp': timestamp_iso, 'summary': summary, 'key': storage_key, 'storage': storage_name})
        else: # 다른 저장소들은 단일 구조로 가정
            for storage_key, data_item in storage_dict.items():
                 metadata = data_item.get('metadata', {})
                 if metadata.get('name') == name and metadata.get('phone') == phone and metadata.get('region') == region:
                     timestamp_iso = data_item.get('timestamp')
                     summary = data_item.get('summary')
                     if timestamp_iso and summary:
                         found_summaries.append({'timestamp': timestamp_iso, 'summary': summary, 'key': storage_key, 'storage': storage_name})

    # 찾은 요약이 없으면 None 반환
    if not found_summaries:
        print("ℹ️ 일치하는 이전 요약 내용 없음 (모든 저장소).")
        return None

    # 찾은 요약들을 시간순으로 정렬 (최신순)
    def get_datetime_from_iso(iso_str):
        """ ISO 문자열을 datetime 객체로 변환 (오류 시 최소값 반환) """
        try:
            dt = datetime.fromisoformat(iso_str)
            # 시간대 정보가 없으면 UTC로 통일 (비교 위해)
            if dt.tzinfo is None:
                 dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
             return datetime.min.replace(tzinfo=timezone.utc) # 파싱 불가 시 맨 뒤로

    found_summaries.sort(key=lambda x: get_datetime_from_iso(x['timestamp']), reverse=True)

    # 가장 최신 요약 정보 가져오기
    latest_summary_info = found_summaries[0]
    print(f"✅ 가장 최신 요약 내용 발견 ({latest_summary_info['storage']} Key: {latest_summary_info['key']}, Timestamp: {latest_summary_info['timestamp']})")

    return latest_summary_info.get('summary', '[요약 없음]')



# === _process_summary_item Helper Function (Formats items for lists) ===
# 이 함수는 storage_key와 원본 data_item을 받아서 목록에 표시할 형태로 가공합니다.
# _filter_and_process_list 에서 호출됩니다.
# endpoint 함수들 외부에 정의되어야 합니다.
def _process_summary_item(storage_key, data_item):
    """Helper to format a single summary item from storage for list APIs"""
    # 이 함수는 data_item이 raw dictionary라고 가정합니다.
    try:
        # data_item이 유효한 딕셔너리인지 확인
        if not isinstance(data_item, dict):
             # print(f"WARN: _process_summary_item called with non-dict item: {storage_key}")
             return None # 딕셔너리가 아니면 건너뛰기


        # data_item의 메타데이터 확인
        metadata = data_item.get('metadata', {})
        source = data_item.get('source', 'unknown')
        timestamp_iso = data_item.get('timestamp')
        summary_text = data_item.get('summary', '[Summary Missing]')
        name = metadata.get('name', 'N/A')
        phone = metadata.get('phone', 'N/A')
        region = metadata.get('region', 'N/A')
        # 데이터에 저장된 이메일 정보들 (업로드/녹음 시 저장했어야 합니다.)
        item_client_email = metadata.get('email', 'N/A') # 대상 의뢰인 이메일
        original_uploader_email = metadata.get('uploader_email', 'N/A') # 원본 업로더 이메일
        item_topic = metadata.get('key_topic', 'N/A') # 토픽 정보


        # Only process items that originated from uploads/records/admin_uploads
        if source and (source.startswith('upload') or source.startswith('record') or source.startswith('admin_upload')):

            formatted_date = "N/A"
            sort_timestamp = None

            if timestamp_iso:
                try:
                    from datetime import datetime # 필요시 임포트 (상단에 이미 임포트됨)
                    dt_object = datetime.fromisoformat(timestamp_iso)
                    formatted_date = dt_object.strftime('%Y-%m-%d %H:%M:%S')
                    sort_timestamp = dt_object
                except ValueError:
                     # print(f"WARN: 유효하지 않은 타임스탬프 형식 (키: {storage_key}): {timestamp_iso}")
                     formatted_date = timestamp_iso
                     # sort_timestamp = datetime.min # 정렬을 위해 기본값 설정 고려

            # API 응답 목록에 포함시킬 항목 딕셔너리 구성
            # 이 딕셔너리가 클라이언트 측 JS (plaint.js 등)에서 각 행을 채우는 데 사용됩니다.
            return {
                'storage_key': storage_key,
                'name': name,
                'phone': phone,
                'region': region,
                'date_created': formatted_date, # yyyy-mm-dd HH:MM:SS 형식
                'source': source,
                'summary': summary_text, # 목록에 요약 포함 (필요 없다면 제거)
                'user_email': item_client_email, # 대상 의뢰인 이메일 (클라이언트에서 필요시 사용)
                'original_uploader_email': original_uploader_email, # 원본 업로더 이메일 (클라이언트에서 필요시 사용)
                'key_topic': item_topic, # 항목의 토픽 정보 (클라이언트에서 종류별 필터링 시 사용)
                # 'processing_status': data_item.get('processing_status', 'N/A'), # 처리 상태 정보도 필요시 추가
                # 'requester_email': requester_email, # 요청자 이메일을 각 항목에 포함 (선택적)
                'sort_timestamp': sort_timestamp # 정렬 목적 (반환 시 제거)
            }
        else:
             # print(f"DEBUG: 예상치 못한 출처 항목 스킵: 키={storage_key}, 출처={source}")
             return None # 예상치 못한 출처의 항목은 건너뛰기
    except Exception as e:
         print(f"🚨 목록 항목 처리 오류 (키: {storage_key}): {e}")
         traceback.print_exc()
         return None # 항목 처리 중 오류 발생 시 건너뛰기
def parse_filename(filename):
    """
    파일명을 파싱하여 이름, 전화번호, 지역, 날짜, 파일 타입을 추출합니다.
    예상 형식: 이름_전화번호_지역_YYYY-MM-DD_타입[_NN].txt
    (타입: summary 또는 original, _NN은 타입 뒤에 오는 선택적 숫자 접미사)
    """
    try:
        base_name, ext = os.path.splitext(filename)
        if ext != ".txt":
            return None

        original_file_identifier = filename
        parts = base_name.split('_')

        file_type = "unknown"
        number_suffix = None

        # 1. ✨ 숫자 접미사 (_NN) 추출 시도 (맨 끝 부분) ✨
        if len(parts) > 0 and re.fullmatch(r'\d+', parts[-1]):
            # 마지막 부분이 숫자로만 이루어져 있다면 숫자 접미사로 간주하고 제거
            number_suffix = parts.pop(-1)
            # print(f"DEBUG: Found potential number suffix '{number_suffix}' in {filename}")

        # 2. ✨ 타입 추출 시도 (숫자 제거 후 맨 끝 부분) ✨
        if len(parts) > 0 and parts[-1] in ['summary', 'original']:
            file_type = parts.pop(-1)
        # else: # 타입이 없으면 그냥 넘어감 (file_type은 'unknown' 유지)
            # print(f"DEBUG: No type found for {filename} after removing number.")

        # 3. 날짜 형식 확인 및 추출 (타입 제거 후 맨 끝 부분)
        file_date_str = None
        if len(parts) > 0 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[-1]):
            file_date_str = parts.pop(-1)

        # 4. 지역 추출 (전화번호 앞에 있다고 가정 - 이전 로직 유지 또는 개선)
        region = None
        if len(parts) > 1 : # 이름, 번호, 지역 위한 최소 길이 확인
            # 마지막 남은 부분이 전화번호 형식인지 확인
            if re.fullmatch(r"[\d-]+", parts[-1]):
                # 전화번호 형식이라면 그 앞부분(있다면)이 지역
                if len(parts) > 1:
                    region = parts.pop(-2) # 전화번호 앞 부분을 지역으로 사용하고 제거
            else:
                 # 전화번호 형식이 아니라면 지역일 수 있음 (더 단순한 경우)
                 region = parts.pop(-1)


        # 5. 전화번호 추출 (지역 제거 후 맨 끝 부분)
        phone = None
        if len(parts) > 0 and re.fullmatch(r"[\d-]+", parts[-1]):
            phone = parts.pop(-1)

        # 6. 나머지 부분을 이름으로 조합
        name = "_".join(parts) if parts else "알수없음"

        # --- 기본값 처리 ---
        if not name: name = "이름없음"
        if not phone: phone = "번호없음"
        if not region: region = "지역없음"
        if not file_date_str: file_date_str = "날짜없음"
        # file_type은 위에서 처리됨 (기본값 'unknown')

        parsed_data = {
            "name": name,
            "phone": phone,
            "region": region,
            "date": file_date_str,
            "type": file_type,
            "original_filename": original_file_identifier # ✨ 실제 전체 파일명을 포함
        }
        # print(f"DEBUG: Parsed {filename} -> {parsed_data}")
        return parsed_data

    except Exception as e:
        print(f"⚠️ 파일명 파싱 오류 ({filename}): {e}")
        print(traceback.format_exc()) # 상세 오류 추적
        return {
            "name": filename, # 파싱 실패 시 원본 파일명을 이름으로 사용
            "phone": "N/A",
            "region": "N/A",
            "date": "N/A",
            "type": "parse_error",
            "original_filename": filename # ✨ 실제 전체 파일명 포함
        }

def _create_summary_list(storage_dict, requester_email, required_topic=None):
    """
    user_memory_storage를 순회하며, 요청자의 이메일/관리자 상태 및 필수 토픽으로 필터링하여 요약 목록을 생성합니다.
    user_memory_storage는 {의뢰인_이메일: {storage_key: data_item, ...}, ...} 구조이며,
    data_item에는 metadata에 'email'(대상 의뢰인), 'uploader_email'(원본 업로더), 'key_topic'이 저장되어 있다고 가정합니다.
    """
    summaries_list = []
    # storage_dict 는 이제 user_memory_storage 자체를 기대합니다.
    if storage_dict is None:
        print(f"DEBUG: _create_summary_list called with None storage_dict.")
        return summaries_list # user_memory_storage 가 None이면 빈 목록 반환

    # Simple mock admin check (replace with real logic if needed)
    is_admin = (requester_email == 'admin@example.com') # TODO: 실제 관리자 확인 로직으로 변경


    # user_memory_storage (storage_dict)는 {의뢰인_이메일: {storage_key: data_item, ...}, ...} 형태입니다.
    # 의뢰인 이메일 키들 (client_email_key)을 순회합니다.
    if not isinstance(storage_dict, dict): # user_memory_storage가 딕셔너리가 아니면 오류
        print(f"ERROR: _create_summary_list expected a dictionary (user_memory_storage) but got {type(storage_dict)}")
        return [] # 오류 발생 시 빈 목록 반환

    for client_email_key, client_data_dict in storage_dict.items():
        # 각 의뢰인의 데이터 딕셔너리가 유효한지 확인
        if not isinstance(client_data_dict, dict):
            print(f"WARN: user_memory_storage의 '{client_email_key}' 키 아래 데이터가 유효한 딕셔너리가 아님. 스킵.")
            continue # 유효한 딕셔너리가 아니면 건너뛰기

        # 이 의뢰인의 데이터 딕셔너리 (client_data_dict)를 순회합니다.
        for storage_key, data_item in client_data_dict.items():
            try:
                # 데이터 항목이 유효한 딕셔너리인지 확인
                if not isinstance(data_item, dict):
                     print(f"WARN: '{client_email_key}' 아래 저장소에 유효하지 않은 항목 스킵: {storage_key}")
                     continue # 딕셔너리가 아니면 건너뛰기


                # 항목의 메타데이터 가져오기
                metadata = data_item.get('metadata', {})
                target_client_email_in_data = metadata.get('email') # 데이터에 저장된 대상 의뢰인 이메일
                original_uploader_email = metadata.get('uploader_email') # 데이터에 저장된 원본 업로더 이메일
                item_topic = metadata.get('key_topic') # 데이터에 저장된 항목 토픽


                # --- 필터링 로직 ---
                # 1. 이 항목의 토픽이 요청된 토픽(required_topic)과 일치하는가? (required_topic이 지정된 경우에만 확인)
                topic_matches = (required_topic is None) or (item_topic == required_topic)

                # 2. 이 항목에 대해 요청한 사용자가 볼 권한이 있는가?
                #    a) 요청한 사용자가 이 항목의 '대상 의뢰인' 본인인가? (요청자 이메일 == 데이터의 대상 의뢰인 이메일)
                #    b) 요청한 사용자가 '원본 업로더' 본인인가? (메타데이터 'uploader_email' 일치)
                #    c) 요청한 사용자가 '관리자 역할'을 가지고 있는가? (관리자 역할 체크)

                is_owner = (requester_email != '이메일 정보 없음' and target_client_email_in_data == requester_email) # 대상 의뢰인 본인인지 확인
                is_original_uploader = (requester_email != '이메일 정보 없음' and original_uploader_email == requester_email) # 원본 업로더 본인인지 확인
                # is_admin 은 함수 상단에서 이미 확인

                # 항목을 목록에 포함시킬지 결정
                # 토픽이 일치하고 (AND) ( (대상 의뢰인 본인이거나) OR (원본 업로더 이거나) OR (관리자 역할 이거나) )
                if topic_matches and (is_owner or is_original_uploader or is_admin): # 필터링 조건
                     # 필터링 조건을 통과한 항목만 목록에 추가
                     source = data_item.get('source', 'unknown')
                     timestamp_iso = data_item.get('timestamp')
                     summary_text = data_item.get('summary', '[요약 없음]')
                     name = metadata.get('name', 'N/A')
                     phone = metadata.get('phone', 'N/A')
                     region = metadata.get('region', 'N/A')
                     # 목록 항목에 표시할 이메일 정보 (데이터에서 가져옴)
                     item_client_email = target_client_email_in_data
                     item_uploader_email = original_uploader_email


                     formatted_date = "N/A"
                     sort_timestamp = None

                     if timestamp_iso:
                         try:
                             from datetime import datetime # 필요시 임포트
                             dt_object = datetime.fromisoformat(timestamp_iso)
                             formatted_date = dt_object.strftime('%Y-%m-%d %H:%M:%S')
                             sort_timestamp = dt_object
                         except ValueError:
                              formatted_date = timestamp_iso
                              # sort_timestamp = datetime.min # 정렬을 위해 기본값 설정 고려

                     # API 응답 목록에 포함시킬 항목 딕셔너리 구성
                     summaries_list.append({
                         'storage_key': storage_key,
                         'name': name,
                         'phone': phone,
                         'region': region,
                         'date_created': formatted_date,
                         'source': source,
                         'summary': summary_text, # 목록에 요약 포함
                         'user_email': item_client_email, # 대상 의뢰인 이메일 (메타데이터에서)
                         'original_uploader_email': item_uploader_email, # 원본 업로더 이메일 (메타데이터에서)
                         'key_topic_in_data': item_topic, # 항목 토픽 (메타데이터에서)
                         # 'requester_email': requester_email, # 목록 항목별로 요청자 이메일 포함 (선택적)
                         'sort_timestamp': sort_timestamp # 정렬 목적
                     })
                # else: // 필터링 조건을 통과하지 못한 항목은 목록에 추가하지 않음

            except Exception as e: # 특정 항목 처리 중 오류 발생 시
                print(f"🚨 목록 항목 처리 오류 (키: {storage_key}, 요청자: {requester_email}): {e}")
                traceback.print_exc()
                # 오류가 발생한 항목은 건너뛰고 계속 진행

        # 의뢰인 키를 순회하는 바깥쪽 루프 끝

    # 목록 정렬 (선택적)
    try:
        from datetime import datetime # 필요시 임포트
        # sort_timestamp가 None인 경우 datetime.min을 사용하여 리스트 맨 뒤로 보내고, 내림차순 정렬 (최신순)
        summaries_list.sort(key=lambda x: x.get('sort_timestamp') if x.get('sort_timestamp') is not None else datetime.min, reverse=True)
        # 정렬에 사용된 임시 키 제거
        for item in summaries_list:
            item.pop('sort_timestamp', None)
    except Exception as sort_err:
        print(f"WARN: 목록 정렬 오류: {sort_err}")
        # 정렬 실패 시 정렬되지 않은 목록 반환


    return summaries_list


# --- Flask 라우트 ---
@app.route('/')
def index_page():
    """고소장 관련 페이지를 보여주는 라우트 함수"""
    # 고소장 관련 데이터 처리 로직 추가 가능
    return render_template('login.html')    

print("index 실행증")

@app.route('/login')
def login_page():
    """고소장 관련 페이지를 보여주는 라우트 함수"""
    # 고소장 관련 데이터 처리 로직 추가 가능
    return render_template('login.html')
    
@app.route('/main')
def main_page():
    """고소장 관련 페이지를 보여주는 라우트 함수"""
    # 고소장 관련 데이터 처리 로직 추가 가능
    return render_template('index.html')


@app.route('/admin')
def admin_page():
    """관리자 페이지(사이드바 포함된 페이지)를 보여주는 라우트 함수"""
    # 관리자 인증 로직 등 추가 가능
    # admin.html 안에는 {{ url_for('index') }} 와 {{ url_for('plaint_page') }} 링크가 포함됨
    return render_template('admin.html')

@app.route('/plaint') # 원하는 URL 경로 지정
def plaint_page():
    # 필요한 로직 추가 (예: 사용자 인증 확인 등)
    return render_template('plaint.html')

@app.route('/supplementaries')
def supplementary_page():
    """보충이유서 페이지(사이드바 포함된 페이지)를 보여주는 라우트 함수"""
    # 관리자 인증 로직 등 추가 가능
    # admin.html 안에는 {{ url_for('index') }} 와 {{ url_for('plaint_page') }} 링크가 포함됨
    return render_template('supplementary.html')

@app.route('/prosecutor')
def prosecutor_page():
    """검찰의견서 페이지(사이드바 포함된 페이지)를 보여주는 라우트 함수"""
    # 관리자 인증 로직 등 추가 가능
    # admin.html 안에는 {{ url_for('index') }} 와 {{ url_for('plaint_page') }} 링크가 포함됨
    return render_template('prosecutor.html')


# app.py 또는 server.py 파일 내용 중

@app.route("/api/complaints")
def list_complaints():
    """고소장 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
    id_token = None
    uploader_uid = None # 요청자 UID (로깅용)
    requester_email = '이메일 정보 없음' # 요청자 이메일

    # user_memory_storage 전역 변수 사용 명시 ▼▼▼
    global user_memory_storage

    # auth 객체가 초기화되어 있는지 확인합니다. (실제 auth 또는 Mock)
    if not auth:
        print("🚨 /api/complaints: Firebase Auth object not available.")
        return jsonify({"error": "Server authentication system error"}), 500

    try:
        # --- ▼▼▼ ID 토큰 확인 및 요청자 UID, 이메일 얻기 (필수!) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/complaints: 인증 토큰 없음.")
            # 목록 조회를 위해 인증 필수
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token) # 토큰 검증
            uploader_uid = decoded_token.get('uid') # 요청자 UID (get 사용)
            requester_email = decoded_token.get('email', '이메일 정보 없음') # 요청자 이메일 추출

            if requester_email == '이메일 정보 없음':
                 print("🚨 /api/complaints: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
                 # 필터링을 위해 이메일 필수
                 return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401 # 또는 403

            print(f"ℹ️ /api/complaints 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")
            # 관리자 체크는 _create_summary_list 내부에서 이메일로 수행됩니다.

        except Exception as auth_err: # 토큰 검증/정보 추출 오류
            print(f"🚨 /api/complaints: 토큰 검증 오류: {auth_err}")
            traceback.print_exc()
            is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
            error_status_code = 401 if is_invalid_token_error else 500
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 요청자 UID, 이메일 얻기 ▲▲▲ ---

        # --- 인증 통과 후 로직 수행 (데이터 필터링) ---
        print(f"--- '/api/complaints' 데이터 조회 시작 (요청자: {requester_email}) ---")
        # user_memory_storage 전체에서 고소장 목록을 가져오되, 요청자의 이메일과 토픽("고소장")으로 필터링 ▼▼▼
        # _create_summary_list 함수는 다른 곳에 정의되어 있으며, user_memory_storage 구조를 탐색하고 필터링합니다.
        data = _create_summary_list(user_memory_storage, requester_email, required_topic="고소장") # <--- 조회 대상을 user_memory_storage로 변경

        print(f"--- '/api/complaints' 처리 완료, {len(data)}개 항목 반환 ---")
        return jsonify(data)

    except Exception as e:
        print(f"🚨 고소장 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그에 요청자 이메일 포함
        traceback.print_exc()
        return jsonify({"error":"고소장 목록 생성 실패", "detail": str(e)}), 500
    
# app.py 또는 server.py 파일 내용 중

@app.route("/api/supplementaries")
def list_supplementaries():
    """보충이유서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
    id_token = None
    uploader_uid = None
    requester_email = '이메일 정보 없음'

    # user_memory_storage 전역 변수 사용 명시 ▼▼▼
    global user_memory_storage

    if not auth:
        print("🚨 /api/supplementaries: Firebase Auth object not available.")
        return jsonify({"error": "Server authentication system error"}), 500

    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/supplementaries: 인증 토큰 없음.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token.get('uid')
            requester_email = decoded_token.get('email', '이메일 정보 없음')

            if requester_email == '이메일 정보 없음':
                 print("🚨 /api/supplementaries: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
                 return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401

            print(f"ℹ️ /api/supplementaries 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")

        except Exception as auth_err:
            print(f"🚨 /api/supplementaries: 토큰 검증 오류: {auth_err}")
            traceback.print_exc()
            is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
            error_status_code = 401 if is_invalid_token_error else 500
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500

        print(f"--- '/api/supplementaries' 데이터 조회 시작 (요청자: {requester_email}) ---")
        # user_memory_storage 전체에서 보충이유서 목록을 가져오되, 요청자의 이메일과 토픽("보충이유서")으로 필터링 ▼▼▼
        data = _create_summary_list(user_memory_storage, requester_email, required_topic="보충이유서") # <--- 조회 대상을 user_memory_storage로 변경

        print(f"--- '/api/supplementaries' 처리 완료, {len(data)}개 항목 반환 ---")
        return jsonify(data)

    except Exception as e:
        print(f"🚨 보충이유서 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그에 요청자 이메일 포함
        traceback.print_exc()
        return jsonify({"error":"보충이유서 목록 생성 실패", "detail": str(e)}), 500

# === 검찰의견서 목록 반환 엔드포인트 (/api/prosecutor) ===
# 이 엔드포인트는 user_memory_storage에서 검찰의견서(required_topic="검찰의견서") 목록을 필터링하여 반환합니다.
# app.py 또는 server.py 파일 내용 중

# app.py 또는 server.py 파일 내용 중

@app.route("/api/prosecutor")
def list_prosecutor_opinions():
    """검찰의견서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
    id_token = None
    uploader_uid = None
    requester_email = '이메일 정보 없음'

    # user_memory_storage 전역 변수 사용 명시 ▼▼▼
    global user_memory_storage

    if not auth:
        print("🚨 /api/prosecutor: Firebase Auth object not available.")
        return jsonify({"error": "Server authentication system error"}), 500

    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/prosecutor: 인증 토큰 없음.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token.get('uid')
            requester_email = decoded_token.get('email', '이메일 정보 없음')

            if requester_email == '이메일 정보 없음':
                 print("🚨 /api/prosecutor: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
                 return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401

            print(f"ℹ️ /api/prosecutor 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")

        except Exception as auth_err:
            print(f"🚨 /api/prosecutor: 토큰 검증 오류: {auth_err}")
            traceback.print_exc()
            is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
            error_status_code = 401 if is_invalid_token_error else 500
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500

        print(f"--- '/api/prosecutor' 데이터 조회 시작 (요청자: {requester_email}) ---")
        # user_memory_storage 전체에서 검찰의견서 목록을 가져오되, 요청자의 이메일과 토픽("검찰의견서")으로 필터링 ▼▼▼
        data = _create_summary_list(user_memory_storage, requester_email, required_topic="검찰의견서") # <--- 조회 대상을 user_memory_storage로 변경

        print(f"--- '/api/prosecutor' 처리 완료, {len(data)}개 항목 반환 ---")
        return jsonify(data)

    except Exception as e:
        print(f"🚨 검찰의견서 목록 생성 오류 (요청자: {requester_email}): {e}")
        traceback.print_exc()
        return jsonify({"error":"검찰의견서 목록 생성 실패", "detail": str(e)}), 500


user_memory_storage = {}  # /upload, /record 결과 저장용
admin_memory_storage = {} # /admin/upload 결과 저장용
complaint_storage = {}
supplementary_storage = {}  # <--- 이 이름이 정확한지 확인!
prosecutor_opinion_storage = {}

def sanitize_filename(name): return re.sub(r'[\\/*?:"<>|]', "", name)
def get_unique_filename(directory, base_name, extension):
    os.makedirs(directory, exist_ok=True)
    counter = 0
    file_path = os.path.join(directory, f"{base_name}{extension}")
    while os.path.exists(file_path):
        counter += 1
        file_path = os.path.join(directory, f"{base_name}_{counter:02d}{extension}")
    return file_path
def parse_filename(filename): # 예시 구현
    parts = os.path.splitext(filename)[0].split('_')
    if len(parts) >= 5:
        type_part = parts[-1]
        date_part = parts[-2] if parts[-1].isdigit() else parts[-1] # Handle _NN suffix
        date_part_index = -2 if parts[-1].isdigit() else -1
        region_part = parts[date_part_index -1]
        phone_part = parts[date_part_index -2]
        name_part = "_".join(parts[:date_part_index -2])

        file_type = "unknown"
        # Adjust type detection based on potentially complex suffixes (_admin_summary_01.txt)
        filename_lower = filename.lower()
        if "_admin_summary" in filename_lower: file_type = "admin_summary"
        elif "_summary" in filename_lower: file_type = "summary"
        elif "_original" in filename_lower: file_type = "original"
        elif "_admin_audio" in filename_lower: file_type = "admin_audio"
        elif "_admin_ref" in filename_lower: file_type = "admin_ref"

        return {
            "filename": filename, "name": name_part, "phone": phone_part,
            "region": region_part, "date": date_part, "type": file_type
        }
    return None

# --- 헬퍼 플레이스홀더 끝 ---


# --- 라우트 수정 ---



@app.route("/upload", methods=['POST'])
def upload_file():
    """ID 토큰 인증 -> STT -> 요약 -> user_memory_storage 저장"""
    global user_memory_storage
    storage_key = None; uploader_uid = None; temp_file_path = None; uploader_email = '이메일 정보 없음';
    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        id_token = None
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]

        if not id_token:
            print("🚨 /upload: Authorization 헤더 없거나 Bearer 토큰 아님.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        try:
            # ID 토큰 검증
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # <<< 로그인된 사용자의 UID 획득!
            uploader_email = decoded_token.get('email', '이메일 정보 없음') # <--- 추가된 부분
            print(f"ℹ️ /upload 요청 사용자 UID (ID Token): {uploader_uid}, Email: {uploader_email}") # <--- 로그 수정 (이메일 추가)
        except auth.InvalidIdTokenError as e:
            print(f"🚨 /upload: 유효하지 않은 ID 토큰: {e}")
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e: # 토큰 검증 중 다른 오류
             print(f"🚨 /upload: 토큰 검증 오류: {e}")
             return jsonify({"error": "토큰 검증 중 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 ▲▲▲ ---

        # --- 2. 입력 유효성 검사 ---
        required_fields = ['name', 'phone', 'region']
        if 'file' not in request.files: return jsonify({'error': '오디오 파일이 필요합니다.'}), 400
        file_object_for_clova = request.files['file']
        if not file_object_for_clova or file_object_for_clova.filename == '': return jsonify({'error': '유효한 오디오 파일을 선택해 주세요.'}), 400
        missing_fields = [f for f in required_fields if f not in request.form or not request.form[f]]
        if missing_fields: return jsonify({'error': f"필수 필드 누락: {', '.join(missing_fields)}"}), 400
        name, phone, region = request.form['name'], request.form['phone'], request.form['region']

        # --- 3. 메모리 저장 키 생성 (UID는 키에 미포함) ---
        safe_name=sanitize_filename(name); safe_phone=sanitize_filename(phone); safe_region=sanitize_filename(region)
        base_file_name_prefix = f"{safe_name}_{safe_phone}_{safe_region}_{str(date.today())}"
        # 시간 기반 고유 키 생성
        storage_key = f"{base_file_name_prefix}_{datetime.now().strftime('%H%M%S%f')}"
        print(f"ℹ️ User 메모리 저장소 키 생성: {storage_key} (User: {uploader_email})")

        # --- 4. 임시 오디오 파일 생성 (Clova 호출용) ---
        original_extension = os.path.splitext(file_object_for_clova.filename)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=original_extension) as temp_audio_file:
            file_object_for_clova.save(temp_audio_file.name)
            temp_file_path = temp_audio_file.name
            print(f"✅ 임시 파일 저장됨: {temp_file_path}")

        # (디버그 로그: 임시 파일 크기 확인 등)
        if temp_file_path and os.path.exists(temp_file_path):
             try: print(f"DEBUG: Clova 전송 파일: {temp_file_path}, 크기: {os.path.getsize(temp_file_path)} bytes")
             except Exception as e: print(f"DEBUG: 파일 크기 확인 오류: {e}")

        # --- 5. Clova API 호출 ---
        print(f"⏳ Clova STT 요청 (임시 파일: {temp_file_path})...")
        clova_client = ClovaSpeechClient() # Clova 클라이언트 인스턴스화
        res = clova_client.req_upload(file=temp_file_path, completion='sync', diarization=True)
        clova_response_text = res.text
        print(f"✅ Clova 응답 상태코드: {res.status_code}")
        print(f"DEBUG: Clova 응답 (앞 500자): {clova_response_text[:500]}")

        # --- 6. 임시 오디오 파일 삭제 ---
        if temp_file_path and os.path.exists(temp_file_path):
            try: os.remove(temp_file_path); print(f"🧹 임시 오디오 파일 삭제됨: {temp_file_path}")
            except OSError as e: print(f"🚨 임시 오디오 파일 삭제 실패: {e}")
        temp_file_path = None # 경로 변수 초기화

        # --- 7. 결과 처리 및 저장 ---
        if res.status_code == 200:
            # STT 결과 처리
            result_data = res.json()
            transcribed_text = ""
            if 'segments' in result_data and result_data['segments']:
                 texts_by_speaker=[f"화자 {s.get('speaker',{}).get('label','?')}: {s.get('text','')}" for s in result_data['segments']]
                 transcribed_text="\n".join(texts_by_speaker)
            elif 'text' in result_data: transcribed_text=result_data.get('text','변환된 텍스트 없음')
            else: transcribed_text='Clova 응답에 텍스트 데이터 없음'
            print(f"--- Clova 변환 결과 ---\n{transcribed_text[:1000]}...\n-----------------------")

            # Gemini 요약 호출
            print(f"DEBUG: Gemini 요약 호출 (키: {storage_key})")
            gemini_summary = summarize_text_with_gemini(transcribed_text)
            print(f"DEBUG: Gemini 요약 결과 (키: {storage_key}): '{str(gemini_summary)[:100]}...'")
            current_timestamp_iso = datetime.now().isoformat()
            print(f"DEBUG: 저장될 타임스탬프 (키: {storage_key}): {current_timestamp_iso}")

            # --- ▼▼▼ 사용자 UID 기반 중첩 저장 ▼▼▼ ---
            # 해당 사용자 UID의 "폴더"(딕셔너리)가 없으면 생성
            if uploader_uid not in user_memory_storage:
                user_memory_storage[uploader_uid] = {}
                print(f"DEBUG: Created new user folder in memory for UID: {uploader_uid}")

            # 해당 사용자 폴더 안에 데이터 저장 (uid 필드 불필요)
            user_memory_storage[uploader_uid][storage_key] = {
                'original': transcribed_text,
                'summary': gemini_summary,
                'source': 'upload (tempfile)', # 출처 명시
                'timestamp': current_timestamp_iso,
                # 'uid' 필드는 이제 상위 키가 UID이므로 저장 안 함
                'metadata': {
                    'name': name,
                    'phone': phone,
                    'region': region,
                    'original_filename': file_object_for_clova.filename,
                    'user_email': uploader_email
                 }
            }
            print(f"✅ User 메모리에 저장됨 (UID: {uploader_uid}, Email: {uploader_email}, Key: {storage_key})")
            # --- ▲▲▲ 사용자 UID 기반 중첩 저장 ▲▲▲ ---

            # 로컬 텍스트 파일은 저장하지 않음

            # 성공 응답 반환
            return jsonify({
                'message':'처리 완료 (메모리 저장)',
                'storage_key':storage_key,
                'original_text':transcribed_text, # 프론트에서 즉시 필요시 반환
                'summary':gemini_summary,
                'user_email': uploader_email        # 프론트에서 즉시 필요시 반환
            }), 200
        else:
            # Clova API 실패 처리
            print(f"🚨 Clova API 실패 ({res.status_code}). 응답: {clova_response_text[:200]}...")
            return jsonify({'error': 'Clova 음성 인식 실패', 'detail': clova_response_text}), res.status_code

    except Exception as e:
        # --- 전체 예외 처리 ---
        print(f"🚨 예외 발생 (upload): {e}"); print(traceback.format_exc())

        # 임시 오디오 파일 정리
        if temp_file_path and os.path.exists(temp_file_path):
            try: os.remove(temp_file_path); print(f"🧹 오류로 임시 오디오 삭제: {temp_file_path}")
            except OSError as e_rem: print(f"🚨 오류 시 임시 오디오 삭제 실패: {e_rem}")

        # --- ▼▼▼ 중첩 구조 메모리 정리 ▼▼▼ ---
        if uploader_uid and storage_key and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
            try:
                del user_memory_storage[uploader_uid][storage_key]
                print(f"🧹 오류로 User 메모리 삭제 (UID: {uploader_uid}, Key: {storage_key})")
                # 해당 사용자 데이터가 모두 삭제되어 폴더가 비었는지 확인 후 폴더 자체 삭제 (선택적)
                if not user_memory_storage[uploader_uid]:
                    del user_memory_storage[uploader_uid]
                    print(f"🧹 빈 사용자 폴더 삭제됨 (UID: {uploader_uid})")
            except KeyError:
                 print(f"🧹 오류 발생 시 메모리 정리 중 Key 이미 없음 (UID: {uploader_uid}, Key: {storage_key})")
        # --- ▲▲▲ 중첩 구조 메모리 정리 ▲▲▲ ---

        return jsonify({'error': '서버 내부 오류', 'exception': str(e)}), 500

@app.route("/record", methods=['POST'])
def record_audio():
    """웹 녹음 처리 (WebM->WAV->STT->요약-> user_memory_storage 저장) + ID 토큰 인증 (필수)"""
    global user_memory_storage
    temp_webm_path, temp_wav_path, storage_key = None, None, None
    # id_token = None # id_token 변수는 검증 후 사용하지 않으므로 제거 가능
    uploader_uid = None # 항상 UID를 얻어야 함
    uploader_email = '이메일 정보 없음'
    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증 필수) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        id_token = None
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]

        # 1. 토큰 존재 여부 확인 (없으면 401)
        if not id_token:
            print("🚨 /record: Authorization 헤더 없거나 Bearer 토큰 아님.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        # 2. 토큰 검증 (실패 시 401 또는 500)
        try:
            # ID 토큰 검증 (auth 객체가 초기화되어 있어야 함)
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # <<< 로그인된 사용자의 UID 획득!
            uploader_email = decoded_token.get('email', '이메일 정보 없음')
            print(f"ℹ️ /record 요청 사용자 UID (ID Token): {uploader_uid}, Email: {uploader_email}")
        except auth.InvalidIdTokenError as e:
            print(f"🚨 /record: 유효하지 않은 ID 토큰: {e}")
            # 유효하지 않은 토큰이므로 401 반환
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e: # 토큰 검증 중 다른 오류
            print(f"🚨 /record: 토큰 검증 오류: {e}")
            # 기타 검증 오류 시 500 반환
            return jsonify({"error": "토큰 검증 중 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 ▲▲▲ ---
        # 이 시점 이후에는 uploader_uid 가 항상 유효한 값이어야 함

        # --- 라이브러리 및 입력 유효성 검사 ---
        if not PYDUB_AVAILABLE:
            # 실제 운영에서는 서버 시작 시점에 확인하거나, 에러 발생 시 로깅 후 500 반환
            print("🚨 /record: pydub 라이브러리를 사용할 수 없습니다.")
            return jsonify({'error': '서버 설정 오류 (오디오 처리 불가)'}), 500
            # raise ImportError("pydub 라이브러리 없음") # 또는 예외 발생

        required_fields = ['name', 'phone', 'region']
        if 'file' not in request.files: return jsonify({'error': '오디오 파일(WebM) 필요'}), 400
        webm_file = request.files['file']
        if not webm_file or webm_file.filename == '': return jsonify({'error': '유효한 오디오 파일 선택'}), 400
        missing_fields = [f for f in required_fields if f not in request.form or not request.form[f]]
        if missing_fields: return jsonify({'error': f"필수 필드 누락: {', '.join(missing_fields)}"}), 400
        name, phone, region = request.form['name'], request.form['phone'], request.form['region']

        # --- 저장 키 생성 (/upload와 동일한 네이밍 + _rec 접미사) ---
        safe_name=sanitize_filename(name); safe_phone=sanitize_filename(phone); safe_region=sanitize_filename(region)
        # _rec 접미사를 추가하여 upload와 구분 가능하도록 함 (선택적)
        base_file_name_prefix = f"{safe_name}_{safe_phone}_{safe_region}_{str(date.today())}_rec"
        storage_key = f"{base_file_name_prefix}_{datetime.now().strftime('%H%M%S%f')}"
        # 로그: 사용자 UID는 이제 항상 존재
        print(f"ℹ️ User 메모리 저장소 키 (녹음): {storage_key} (User: {uploader_email})")

        # --- 오디오 처리 (WebM -> WAV) ---
        # 임시 WebM 저장
        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_webm_file:
            webm_file.save(temp_webm_file.name); temp_webm_path = temp_webm_file.name
            print(f"✅ 임시 WebM 저장: {temp_webm_path}")

        # WebM -> WAV 변환 (임시 WAV 생성)
        try:
            print(f"⏳ WAV 변환 시도: {temp_webm_path}...")
            audio = AudioSegment.from_file(temp_webm_path, format="webm")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_wav_file:
                # export 시에도 예외 발생 가능성 고려
                audio.export(temp_wav_file.name, format="wav"); temp_wav_path = temp_wav_file.name
                print(f"✅ 임시 WAV 생성: {temp_wav_path}")
        except Exception as e:
            print(f"🚨 /record: WebM -> WAV 변환 실패: {e}")
            # 변환 실패 시 관련 임시 파일 정리 후 오류 반환
            if temp_webm_path and os.path.exists(temp_webm_path):
                try: os.remove(temp_webm_path); print(f"🧹 (변환실패) 임시 WebM 삭제: {temp_webm_path}")
                except OSError as e_rem: print(f"🚨 (변환실패) 임시 WebM 삭제 실패: {e_rem}")
            return jsonify({'error': '오디오 파일 변환 실패', 'detail': str(e)}), 500
        finally:
            # 변환 성공/실패 여부와 관계없이 원본 임시 WebM은 삭제
            if temp_webm_path and os.path.exists(temp_webm_path):
                try: os.remove(temp_webm_path); print(f"🧹 원본 임시 WebM 삭제: {temp_webm_path}")
                except OSError as e: print(f"🚨 임시 WebM 삭제 실패: {e}")
            temp_webm_path = None # 경로 변수 초기화

        # 변환된 WAV 파일 존재 확인
        if not temp_wav_path or not os.path.exists(temp_wav_path):
            # 이 경우는 위의 finally 블록 때문에 발생하기 어려우나 방어적으로 추가
            print("🚨 /record: WAV 변환 후 파일이 존재하지 않음.")
            return jsonify({'error': 'WAV 변환 알 수 없는 오류'}), 500

        # 디버그 로그 (임시 WAV)
        try: print(f"DEBUG: Clova 전송 WAV: {temp_wav_path}, 크기: {os.path.getsize(temp_wav_path)} bytes")
        except Exception as e: print(f"DEBUG: WAV 크기 확인 오류: {e}")

        # --- Clova API 호출 ---
        print(f"⏳ Clova STT 요청 (임시 WAV: {temp_wav_path})...")
        clova_client = ClovaSpeechClient() # 실제 클라이언트 인스턴스화
        res = clova_client.req_upload(file=temp_wav_path, completion='sync', diarization=True)
        clova_response_text = res.text
        print(f"✅ Clova 응답 상태코드 (녹음): {res.status_code}")
        print(f"DEBUG: Clova 응답 (녹음, 앞 500자): {clova_response_text[:500]}")

        # --- 임시 WAV 삭제 ---
        if temp_wav_path and os.path.exists(temp_wav_path):
            try: os.remove(temp_wav_path); print(f"🧹 임시 WAV 삭제: {temp_wav_path}")
            except OSError as e: print(f"🚨 임시 WAV 삭제 실패: {e}")
        temp_wav_path = None # 경로 변수 초기화

        # --- 결과 처리 및 저장 ---
        if res.status_code == 200:
            # STT 결과 처리
            result_data = res.json()
            transcribed_text = ""
            if 'segments' in result_data and result_data['segments']:
                texts_by_speaker=[f"화자 {s.get('speaker',{}).get('label','?')}: {s.get('text','')}" for s in result_data['segments']]
                transcribed_text="\n".join(texts_by_speaker)
            elif 'text' in result_data: transcribed_text=result_data.get('text','변환된 텍스트 없음')
            else: transcribed_text='Clova 응답에 텍스트 데이터 없음'
            print(f"--- Clova 변환 결과 (녹음) ---\n{transcribed_text[:1000]}...\n-----------------------------")

            # Gemini 요약
            print(f"DEBUG: Gemini 요약 호출 (키: {storage_key}, 소스: /record)")
            gemini_summary = summarize_text_with_gemini(transcribed_text)
            current_timestamp_iso = datetime.now().isoformat()
            print(f"DEBUG: 저장될 타임스탬프 (키: {storage_key}): {current_timestamp_iso}")

            # --- ▼▼▼ 사용자 UID 기반 중첩 저장 (/upload와 동일 방식) ▼▼▼ ---
            if uploader_uid not in user_memory_storage:
                user_memory_storage[uploader_uid] = {}
                print(f"DEBUG: Created new user folder in memory for UID: {uploader_uid} (from /record)")

            # 해당 사용자 폴더 안에 데이터 저장 (id_token 필드 제거)
            user_memory_storage[uploader_uid][storage_key] = {
                'original': transcribed_text,
                'summary': gemini_summary,
                'source': 'record (tempfile)', # 출처 명시 (녹음)
                'timestamp': current_timestamp_iso,
                # 'uid'는 상위 키, 'id_token'은 저장 안 함
                'metadata': {
                    'name': name,
                    'phone': phone,
                    'region': region,
                    'original_filename': webm_file.filename, # 원본 WebM 파일명 저장
                    'user_email': uploader_email
                }
            }
            print(f"✅ User 메모리에 저장됨 (UID: {uploader_uid}, Email: {uploader_email}, Key: {storage_key}, Source: /record)")
            # --- ▲▲▲ 사용자 UID 기반 중첩 저장 ▲▲▲ ---

            # 성공 응답 반환
            return jsonify({
                'message':'녹음 처리 완료 (메모리 저장)',
                'storage_key':storage_key,
                'original_text':transcribed_text,
                'summary':gemini_summary,
                'user_email': uploader_email
            }), 200
        else:
            # Clova API 실패 처리
            print(f"🚨 Clova API 실패 ({res.status_code}, 녹음). 응답: {clova_response_text[:200]}...")
            return jsonify({'error': 'Clova 음성 인식 실패', 'detail': clova_response_text}), res.status_code

    # --- 전체 예외 처리 ---
    except Exception as e:
        print(f"🚨 예외 발생 (record): {e}"); print(traceback.format_exc())

        # 임시 파일 정리 (WebM, WAV) - 순서 무관
        if temp_webm_path and os.path.exists(temp_webm_path):
            try: os.remove(temp_webm_path); print(f"🧹 오류로 임시 WebM 삭제: {temp_webm_path}")
            except OSError as e_rem: print(f"🚨 오류 시 임시 WebM 삭제 실패: {e_rem}")
        if temp_wav_path and os.path.exists(temp_wav_path):
            try: os.remove(temp_wav_path); print(f"🧹 오류로 임시 WAV 삭제: {temp_wav_path}")
            except OSError as e_rem: print(f"🚨 오류 시 임시 WAV 삭제 실패: {e_rem}")

        # --- ▼▼▼ 중첩 구조 메모리 정리 (/upload와 동일 방식) ▼▼▼ ---
        if uploader_uid and storage_key and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
            try:
                del user_memory_storage[uploader_uid][storage_key]
                print(f"🧹 오류로 User 메모리 삭제 (UID: {uploader_uid}, Key: {storage_key}, Source: /record)")
                # 해당 사용자 데이터가 모두 삭제되어 폴더가 비었는지 확인 후 폴더 자체 삭제 (선택적)
                if not user_memory_storage[uploader_uid]:
                    del user_memory_storage[uploader_uid]
                    print(f"🧹 빈 사용자 폴더 삭제됨 (UID: {uploader_uid}, Source: /record)")
            except KeyError:
                 print(f"🧹 오류 발생 시 메모리 정리 중 Key 이미 없음 (UID: {uploader_uid}, Key: {storage_key}, Source: /record)")
        # --- ▲▲▲ 중첩 구조 메모리 정리 ▲▲▲ ---

        return jsonify({'error': '서버 내부 오류', 'exception': str(e)}), 500
    



@app.route("/admin/upload", methods=['POST'])
def admin_upload_route_logic():
    """
    관리 인터페이스에서의 파일 업로드 처리.
    관리자 인증 후, 파일 분석 결과를 업로드 수행자의 UID를 primary key로 사용하여
    user_memory_storage에 저장.
    """
    # 사용할 전역 저장소 명시 (실제 운영에서는 DB 사용 권장)
    global user_memory_storage
    # complaint_storage 등 다른 저장소는 사용하지 않도록 수정되었습니다.

    storage_key = None # UserMemory 내 2차 키 (데이터 식별용)
    uploaded_file_metadata_simple = [] # 업로드 파일 정보 요약
    id_token = None
    uploader_uid = None # 업로드 수행자의 UID (관리자 본인)
    uploader_email = '업로더 이메일 정보 없음' # 업로드 수행자의 이메일
    # 대상 의뢰인 정보는 metadata에 저장
    client_email_target = None
    target_name = None
    target_phone = None
    target_region = None
    key_topic = None

    # storage_target_name = None # user_memory_storage만 사용하므로 필요 없음
    success_flag = False # 데이터 저장 성공 플래그
    temp_audio_path = None # 임시 오디오 파일 경로
    temp_doc_paths = [] # 임시 문서 파일 경로 리스트

    print(f"--- '/admin/upload' 요청 처리 시작 ---")

    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID, 이메일 얻기 (업로드 수행자 인증) ▼▼▼ ---
        # 이 로직은 업로드를 수행하는 관리자 사용자의 인증을 확인합니다.
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]

        if not id_token:
            print("🚨 /admin/upload: Authorization 헤더 없거나 Bearer 토큰 아님. 인증 실패.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401
        try:
            # auth 객체가 초기화되어 있어야 함 (Firebase Admin SDK)
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # 업로드 수행자(관리자)의 UID 획득
            uploader_email = decoded_token.get('email', '업로더 이메일 정보 없음') # 이메일 클레임 가져오기

            print(f"ℹ️ /admin/upload 요청 수행자 UID: {uploader_uid}, Email: {uploader_email}")
            # TODO: 관리자 Role 확인 로직이 필요하다면 이 시점에서 추가해야 합니다.
            # 예: if not is_admin(uploader_uid): return jsonify({"error": "관리자 권한이 필요합니다."}), 403

        except auth.InvalidIdTokenError as e:
            print(f"🚨 /admin/upload: 유효하지 않은 ID 토큰: {e}")
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e:
            print(f"🚨 /admin/upload: 업로더 토큰 검증 오류: {e}")
            traceback.print_exc()
            return jsonify({"error": "업로더 토큰 검증 중 서버 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID, 이메일 얻기 ▲▲▲ ---


        # --- 1. 입력 파라미터 및 파일 확인 ---
        # 대상 의뢰인 정보 및 문서 종류(key_topic) 확인
        client_email_target = request.form.get('clientEmail', '').strip() # 대상 의뢰인 이메일 (필요시 메타데이터에 저장)
        target_name = request.form.get('name', '').strip()
        target_phone = request.form.get('phone', '').strip()
        target_region = request.form.get('region', '').strip()
        key_topic = request.form.get('key', '').strip() # 문서 종류 (고소장, 보충 등)

        # 필수 입력 항목 체크 (업로드 수행자의 정보나 파일 관련 항목이 필수일 수 있음)
        # 여기서는 key (문서 종류)와 파일들이 필수라고 가정합니다.
        required_form_fields = {
             'key': '문서 종류 (key)'
             # 'name': '이름', 'phone': '전화번호', 'region': '지역', 'clientEmail': '대상 의뢰인 이메일' # 이 항목들은 필수 여부에 따라 포함
        }
        # 실제로 폼에서 받아와서 키 생성 등에 사용되는 필드들을 모두 체크하는 것이 좋습니다.
        fields_for_key_generation = {
            'name': target_name,
            'phone': target_phone,
            'region': target_region,
            'clientEmail': client_email_target, # 키 생성에 대상 의뢰인 이메일 사용
            'key': key_topic
        }
        missing_fields_for_key = [desc for field, value in fields_for_key_generation.items() for req_field, desc in required_form_fields.items() if field == req_field and not value]

        if missing_fields_for_key:
             print(f"🚨 키 생성에 필요한 필수 입력 누락: {', '.join(missing_fields_for_key)}")
             return jsonify({'error': f'키 생성에 필요한 필수 입력 항목이 누락되었습니다: {", ".join(missing_fields_for_key)}'}), 400


        # 파일 업로드 확인
        if 'audioFile' not in request.files or not request.files['audioFile'].filename:
            print("🚨 오디오 파일 누락 또는 유효하지 않음")
            return jsonify({'error': '오디오 파일(audioFile) 필요'}), 400
        audio_file = request.files['audioFile']

        document_files = request.files.getlist('documentFiles')
        if not document_files or not any(f.filename for f in document_files):
            print("🚨 문서 파일 누락 또는 유효하지 않음")
            return jsonify({'error': '하나 이상의 문서 파일(documentFiles) 필요'}), 400

        # --- 1-1. 대상 의뢰인 UID 조회 로직은 이제 필요 없습니다. (저장 시 업로더 UID 사용) ---
        # 데이터를 저장할 Primary Key는 업로더 UID (uploader_uid)입니다.


        # --- 2. Storage Key 생성 (조회 시 사용될 2차 키) ---
        # 이 키는 user_memory_storage[uploader_uid] 딕셔너리 안에서 데이터를 식별하는 키가 됩니다.
        # 키 생성 시 대상 의뢰인 정보 및 문서 종류 포함 (정보 식별을 위해)
        safe_name = sanitize_filename(target_name)
        safe_phone = sanitize_filename(target_phone)
        safe_region = sanitize_filename(target_region)
        # sanitize_filename 함수가 이메일도 안전하게 처리하도록 구현 필요
        safe_client_email_for_key = sanitize_filename(client_email_target) # 대상 의뢰인 이메일 사용 (키에 포함)

        # 키 생성 시 key_topic 및 의뢰인 이메일 포함하여 명확성 높임
        # 키 포맷: {이름}_{전화번호}_{지역}_{의뢰인이메일}_{날짜}_admin_{토픽}_{시간+마이크로초}
        base_file_name_prefix = f"{safe_name}_{safe_phone}_{safe_region}_{safe_client_email_for_key}_{str(date.today())}_admin_{key_topic}"
        storage_key = f"{base_file_name_prefix}_{datetime.now().strftime('%H%M%S%f')}"
        print(f"ℹ️ 생성된 Storage Key (2차 키): {storage_key} (Topic: {key_topic}, Target Email: {client_email_target}, Uploader: {uploader_email})")


        # --- 3. 파일 임시 처리 및 메타데이터 기록 ---
        audio_filename_secure = secure_filename(audio_file.filename)
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_filename_secure)[1]) as temp_audio:
            audio_file.save(temp_audio.name); temp_audio_path = temp_audio.name
            audio_size = os.path.getsize(temp_audio_path)
            uploaded_file_metadata_simple.append({'type': 'audio', 'original_filename': audio_filename_secure, 'size': audio_size})
            print(f"✅ [AdminRoute] 오디오 임시 저장: {temp_audio_path} ({audio_size} bytes)")

        document_details_for_ocr = []
        for i, doc_file in enumerate(document_files):
            if doc_file and doc_file.filename:
                doc_filename_secure = secure_filename(doc_file.filename)
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(doc_filename_secure)[1]) as temp_doc:
                    doc_file.save(temp_doc.name); temp_doc_path = temp_doc.name
                    temp_doc_paths.append(temp_doc_path) # 임시 파일 경로 리스트에 추가 (finally에서 삭제용)
                    doc_size = os.path.getsize(temp_doc_path)
                    uploaded_file_metadata_simple.append({'type': 'document', 'original_filename': doc_filename_secure, 'size': doc_size})
                    document_details_for_ocr.append({'filename': doc_filename_secure, 'temp_path': temp_doc_path}) # OCR 처리를 위해 파일 정보 저장
                    print(f"✅ [AdminRoute] 문서 임시 저장 ({i+1}): {temp_doc_path} ({doc_size} bytes)")


        # --- 4. Clova STT ---
        transcribed_text = "[STT 결과 없음]"
        if temp_audio_path and os.path.exists(temp_audio_path): # 파일 존재 여부 재확인
            print(f"⏳ [AdminRoute] Clova STT 요청 시작 (파일: {os.path.basename(temp_audio_path)})...") # 파일명만 로깅
            try:
                # ClovaSpeechClient 클래스가 정의되어 있고 사용 준비가 되어 있어야 합니다.
                clova_client = ClovaSpeechClient()
                res = clova_client.req_upload(file=temp_audio_path, completion='sync', diarization=True)
                print(f"✅ [AdminRoute] Clova 상태코드: {res.status_code}")
                if res.status_code == 200:
                    result_data = res.json();
                    # Clova 응답 구조에 따라 텍스트 추출 로직 조정
                    if 'segments' in result_data and result_data['segments']:
                        # 화자 분리 정보가 있는 경우
                        texts_by_speaker = [f"화자 {s.get('speaker',{}).get('label','?')}: {s.get('text','')}" for s in result_data['segments']]
                        transcribed_text = "\n".join(texts_by_speaker)
                    elif 'text' in result_data:
                        # 전체 텍스트만 있는 경우
                        transcribed_text = result_data.get('text','변환된 텍스트 없음')
                    else:
                        transcribed_text = 'Clova 응답에 텍스트 데이터 없음'
                    print(f"✅ [AdminRoute] Clova STT 결과 처리 완료")
                else:
                    transcribed_text = f"[Clova STT 실패: 상태코드 {res.status_code}]"; print(f"🚨 [AdminRoute] Clova STT 실패 ({res.status_code})")
            except Exception as clova_err:
                transcribed_text = f"[Clova API 오류: {clova_err}]"; print(f"🚨 [AdminRoute] Clova API 호출 오류: {clova_err}")
                traceback.print_exc() # API 호출 오류 시 트레이스백 출력
        else:
            print("⚠️ [AdminRoute] 오디오 파일 처리 안됨 또는 임시 파일 없음, STT 건너김.")
        # 오디오 임시 파일 삭제는 finally 블록에서 일괄 처리


        # --- 5. 문서 텍스트 추출 (OCR 등 활용) ---
        all_document_text_parts = []
        print(f"⏳ [AdminRoute] {len(document_details_for_ocr)}개 문서 텍스트 추출 시작...")
        ocr_error_flag = False # OCR 오류 발생 여부 플래그

        # document_details_for_ocr 리스트는 3번 스텝에서 이미 채워져 있습니다.
        for doc_detail in document_details_for_ocr:
            extracted_text = "[문서 텍스트 추출 실패]"
            doc_temp_path = doc_detail.get('temp_path')
            doc_filename = doc_detail.get('filename')

            if doc_temp_path and os.path.exists(doc_temp_path) and doc_filename:
                try:
                    # extract_text_from_file 함수 정의 및 구현 필요 (파일 경로를 받아 텍스트 반환)
                    extracted_text = extract_text_from_file(original_filename=doc_filename, file_path=doc_temp_path)
                    print(f"✅ [AdminRoute] 문서 '{doc_filename}' 텍스트 추출 완료")
                except Exception as ocr_err:
                    print(f"🚨 [AdminRoute] 문서 '{doc_filename}' 텍스트 추출 오류: {ocr_err}")
                    traceback.print_exc()
                    ocr_error_flag = True
            else:
                # 경로/파일명 없음 로그 (3번 스텝에서 이미 경고 로그가 나왔을 수 있음)
                print(f"⚠️ [AdminRoute] 문서 텍스트 추출 건너김: 임시 파일 경로 또는 파일명 누락 ({doc_filename or '파일명 정보 없음'})")
                ocr_error_flag = True # 파일 처리가 제대로 안 된 것도 오류로 간주

            # 결과 통합 시에도 doc_filename 사용
            all_document_text_parts.append(f"--- 문서 시작: {doc_filename or '알수없는 파일'} ---\n{extracted_text}\n--- 문서 끝: {doc_filename or '알수없는 파일'} ---")

        # 문서 임시 파일 삭제는 finally 블록에서 일괄 처리


        # --- 6. 이전 요약 검색 (선택 사항) ---
        # find_previous_summary_content 함수 정의 필요
        # 이 로직은 업로더의 user_memory_storage[uploader_uid] 내에서
        # 대상 의뢰인 정보 (이름, 전화번호 등)를 기반으로 이전 요약을 검색해야 합니다.
        previous_summary_text = find_previous_summary_content(target_name, target_phone, target_region) or "[이전 요약 없음]"
        print(f"ℹ️ 이전 요약 검색 결과: {'찾음' if previous_summary_text != '[이전 요약 없음]' else '없음'}")


        # --- 7. Gemini 분석 ---
        # summarize_with_context 함수 정의 및 Gemini API 호출 로직 구현 필요
        # 입력: STT 결과, 문서 텍스트, 문서 종류(key_topic), 이전 요약
        # 출력: 분석/요약 텍스트
        gemini_analysis = "[Gemini 분석 실패]"
        print(f"⏳ [AdminRoute] Gemini 분석 시작...")
        # Gemini 모델에 전달할 문서 텍스트는 하나의 문자열로 결합하는 것이 일반적입니다.
        combined_document_text = "\n\n".join(all_document_text_parts)
        try:
            gemini_analysis = summarize_with_context(transcribed_text, combined_document_text, key_topic, previous_summary_text)
            print(f"✅ [AdminRoute] Gemini 분석 완료")
        except Exception as gemini_err:
            print(f"🚨 [AdminRoute] Gemini 분석 오류: {gemini_err}")
            gemini_analysis = f"[Gemini 분석 오류: {gemini_err}]"
            traceback.print_exc() # Gemini 분석 오류 시 트레이스백 출력


        # --- 8. 최종 데이터 객체 생성 (metadata에 대상 의뢰인 정보 및 업로더 정보 포함) ---
        current_timestamp_iso = datetime.now().isoformat()
        data_to_store = {
            'original': transcribed_text, # STT 결과
            'summary': gemini_analysis, # Gemini 분석 결과
            # 조회 시 제거될 필드로 저장하거나, 필요한 경우에만 별도로 제공하는 방식 고려
            # 조회 로직에서 files_content를 pop하므로 여기에 저장하는 것이 좋습니다.
            'files_content': all_document_text_parts, # 문서 텍스트 내용을 files_content로 저장
            'source': f'admin_upload_{key_topic}', # 데이터 출처 및 토픽 명시
            'timestamp': current_timestamp_iso, # 처리 완료 시각
            'metadata': {
                'name': target_name, 'phone': target_phone, 'region': target_region, # 대상 의뢰인 기본 정보 (정보용)
                'email': client_email_target, # <--- 대상 의뢰인 이메일 메타데이터에 저장 (정보용)
                # 'uid': target_client_uid, # 대상 의뢰인 UID는 이제 metadata에 반드시 저장할 필요는 없습니다 (원하면 저장).
                'key_topic': key_topic, # 문서 종류 저장 (고소장, 보충 등)
                'uploaded_files_info': uploaded_file_metadata_simple, # 업로드 파일 정보 (원본 파일명, 크기 등)
                'uploader_uid': uploader_uid, # 업로드 수행자 UID 저장 (누가 업로드했는지 기록 - Primary Key와 동일)
                'uploader_email': uploader_email, # 업로드 수행자 이메일 저장
            },
            'processing_status': '분석 완료' if not ocr_error_flag and transcribed_text != "[STT 결과 없음]" and gemini_analysis != "[Gemini 분석 실패]" else '분석 오류 발생', # 처리 상태 업데이트
        }
        print(f"ℹ️ 저장될 최종 데이터 객체 생성 완료 (상태: {data_to_store['processing_status']})")


        # --- 9. 데이터를 업로드 수행자(관리자)의 user_memory_storage에 저장 ---

        # ⚠️ 핵심: user_memory_storage의 주 키 (Primary Key)로 업로드 수행자의 UID (uploader_uid)를 사용합니다.
        primary_key_for_storage = uploader_uid # <--- 업로드 수행자의 UID 사용!

        # 해당 UID의 딕셔너리가 user_memory_storage에 없으면 생성합니다.
        if primary_key_for_storage not in user_memory_storage:
            user_memory_storage[primary_key_for_storage] = {}
            print(f"DEBUG: Created new memory space for Primary Key (Uploader UID): {primary_key_for_storage}")

        # 해당 UID 딕셔너리 안에 데이터 저장 (storage_key는 두 번째 키로 사용)
        user_memory_storage[primary_key_for_storage][storage_key] = data_to_store

        # === 저장 완료 로그에 저장 정보 표시 ===
        # 로그 메시지 수정: Primary Key가 업로더 UID임을 명시
        print(f"✅ Data successfully saved to user_memory_storage (Primary Key Uploader UID: {primary_key_for_storage}, Secondary Key: {storage_key}, Target Email: {client_email_target or '정보없음'}, Uploader: {uploader_email})") # <--- 로그 수정
        success_flag = True # 저장 성공 플래그 설정


        # === 성공 응답 ===
        # 프론트엔드에게 저장 성공 메시지 및 저장된 데이터의 storage_key를 반환합니다.
        # storage_key는 나중에 이 데이터를 조회할 때 사용됩니다.
        return jsonify({
            'message': f'{key_topic} 처리 및 저장 완료', # 메시지 수정
            'storage_key': storage_key, # 프론트엔드에서 이 키로 데이터를 조회하게 됩니다.
            'uploader_email': uploader_email, # 업로더 이메일 응답 포함 (정보용)
            'uploader_uid': uploader_uid # 업로더 UID 응답 포함 (정보용)
            # 대상 의뢰인 이메일/UID는 응답에 포함할지 결정
            # 'client_email': client_email_target,
            # 'client_uid': target_client_uid, # 대상 의뢰인 UID는 여기서 알 수 없으므로 제외
        }), 200


    except ValueError as ve:
        # 필수 입력 누락 등 ValueError 처리
        print(f"🚨 입력/파일 처리 오류 (/admin/upload): {ve}")
        # traceback.print_exc() # 필요시 상세 오류 추적
        return jsonify({'error': f'입력/파일 처리 오류: {str(ve)}'}), 400
    except Exception as e:
        # 그 외 예상치 못한 서버 내부 오류 발생 시 처리
        print(f"🚨 예외 발생 (/admin/upload): {e}")
        traceback.print_exc() # 서버 콘솔에 전체 스택 트레이스 출력

        # 롤백 로직: 예외 발생 시 user_memory_storage에 저장된 데이터 삭제 시도
        # storage_key가 생성되었고 (즉, 파일 임시 저장 및 키 생성까지 진행되었고)
        # 데이터 저장 성공 플래그(success_flag)가 설정되지 않았을 경우에만 롤백 시도
        if storage_key and not success_flag:
            print(f"ℹ️ 예외 발생, 저장 실패. 롤백 시도 (Storage Key: {storage_key})")
            # 롤백 시 삭제에 필요한 primary_key는 업로더 UID (uploader_uid)입니다.
            # uploader_uid는 try 블록 시작 시점에 이미 얻어졌으므로 바로 사용 가능합니다.
            rollback_primary_key = uploader_uid

            # user_memory_storage에서 데이터 삭제 시도 (UID와 storage_key가 모두 있어야 함)
            if rollback_primary_key and rollback_primary_key in user_memory_storage and storage_key in user_memory_storage[rollback_primary_key]:
                try:
                    del user_memory_storage[rollback_primary_key][storage_key]
                    print(f"🧹 오류 발생으로 user_memory_storage(UID: {rollback_primary_key})에서 데이터 롤백됨: {storage_key}")
                except Exception as del_err:
                     print(f"🚨 롤백 중 user_memory_storage 데이터 삭제 오류 발생 ({storage_key}): {del_err}")
            elif rollback_primary_key:
                 print(f"⚠️ 롤백할 데이터를 user_memory_storage(UID: {rollback_primary_key})에서 찾을 수 없음 (Key: {storage_key}). 이미 삭제되었거나 저장되지 않았을 수 있습니다.")
            else:
                 # 이 경우는 업로더 UID를 얻는 과정에서 예외가 발생했으나 여기서 catch된 경우이며, storage_key도 생성되지 않았을 가능성이 높습니다.
                 print(f"⚠️ 롤백할 데이터를 user_memory_storage에서 찾을 수 없음 (업로더 UID 알 수 없음, Key: {storage_key}).")


        # TODO: 만약 key_topic에 따라 user_memory_storage 외 다른 storage에도 저장하는 로직이 있었다면,
        # 해당 storage에서도 롤백하는 로직을 여기에 추가해야 합니다.
        # 현재 수정된 코드는 user_memory_storage에만 저장하도록 가정하고 있습니다.
        # if storage_key and storage_target_name and not success_flag:
        #     # ... (기존 complaint_storage 등 롤백 로직) ...


        return jsonify({'error': '서버 내부 오류 발생', 'exception': str(e)}), 500
    finally:
        # 임시 파일 최종 정리
        # 오류 발생 여부와 관계없이 함수 종료 시 임시 파일들을 정리합니다.
        print("ℹ️ 임시 파일 정리 시작.")
        if temp_audio_path and os.path.exists(temp_audio_path):
            try: os.remove(temp_audio_path); print(f"🧹 (finally) 오디오 임시 파일 삭제: {temp_audio_path}")
            except OSError as e_rem: print(f"🚨 (finally) 오디오 임시 파일 삭제 실패: {e_rem}")
        for doc_path in temp_doc_paths:
            if doc_path and os.path.exists(doc_path):
                try: os.remove(doc_path); print(f"🧹 (finally) 문서 임시 파일 삭제: {doc_path}")
                except OSError as e_rem: print(f"🚨 (finally) 문서 임시 파일 삭제 실패: {e_rem}")
        print(f"--- '/admin/upload' 요청 처리 완료 ---") # 처리 완료 로그 추가



# ==============================================================================
# === /api/summaries 수정: 인증된 사용자의 데이터만 조회하도록 변경 ===
# ==============================================================================
@app.route("/api/summaries")
def list_summaries():
    """(인증된 사용자) 자신의 메모리 요약 및 메타데이터 목록 반환"""
    all_summaries_data = []
    uploader_uid = None # 인증된 사용자의 UID
    uploader_email = '이메일 정보 없음'
    print(f"--- '/api/summaries' (User Specific Memory) 요청 처리 시작 ---")
    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증 필수) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/summaries: Authorization 헤더가 없거나 Bearer 토큰이 아닙니다. 인증 실패.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]

        try:
            # ID 토큰 검증 (auth 객체가 초기화되어 있어야 함)
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # <<< 로그인된 사용자의 UID 획득!
            uploader_email = decoded_token.get('email', '이메일 정보 없음')
            print(f"ℹ️ /api/summaries 요청 사용자 UID (ID Token): {uploader_uid}, Email: {uploader_email}")
        except auth.InvalidIdTokenError as e:
            print(f"🚨 /api/summaries: 유효하지 않은 ID 토큰: {e}")
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e: # 토큰 검증 중 다른 오류
            print(f"🚨 /api/summaries: 토큰 검증 오류: {e}")
            return jsonify({"error": "토큰 검증 중 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 ▲▲▲ ---

        # --- ▼▼▼ 인증된 사용자의 데이터만 조회 (user_memory_storage[uploader_uid] 접근) ▼▼▼ ---
        # 해당 사용자의 데이터가 없을 경우 빈 딕셔너리 반환 (오류 방지)
        user_specific_data = user_memory_storage.get(uploader_uid, {})
        print(f"DEBUG: Found {len(user_specific_data)} items for user {uploader_uid}")

        for storage_key, data_item in user_specific_data.items():
            try:
                # 각 아이템 처리 (이제 id_token 비교 불필요)
                source = data_item.get('source', 'unknown')

                # source 가 'upload' 또는 'record' 인 경우만 처리 (선택적 강화)
                if source and (source.startswith('upload') or source.startswith('record')):
                    metadata = data_item.get('metadata', {})
                    timestamp_iso = data_item.get('timestamp')
                    summary_text = data_item.get('summary', '[요약 없음]')
                    name = metadata.get('name', 'N/A')
                    phone = metadata.get('phone', 'N/A')
                    region = metadata.get('region', 'N/A')
                    item_email = metadata.get('user_email', uploader_email)
                    formatted_date = "N/A"
                    sort_timestamp = None # 정렬 기준 (datetime 객체)

                    if timestamp_iso:
                        try:
                            # ISO 8601 문자열을 datetime 객체로 변환 (시간대 정보 포함 가능)
                            dt_object = datetime.fromisoformat(timestamp_iso)
                            # 시간대 정보가 없다면 UTC 또는 로컬 시간대로 가정 (일관성 중요)
                            # dt_object = dt_object.replace(tzinfo=timezone.utc) # 예: UTC로 가정
                            formatted_date = dt_object.strftime('%Y-%m-%d %H:%M:%S') # 원하는 형식으로 포맷
                            sort_timestamp = dt_object # 정렬을 위해 datetime 객체 유지
                        except ValueError:
                            print(f"WARN: Invalid timestamp format for key {storage_key}: {timestamp_iso}")
                            formatted_date = timestamp_iso # 변환 실패 시 원본 문자열 사용
                            # 정렬을 위해 에포크 시작 시간 등으로 대체 가능
                            sort_timestamp = datetime.min.replace(tzinfo=timezone.utc)

                    all_summaries_data.append({
                        'storage_key': storage_key,
                        'name': name,
                        'phone': phone,
                        'region': region,
                        'date_created': formatted_date, # 프론트엔드와 키 이름 일치
                        'source': source,
                        'summary': summary_text,
                        'user_email': item_email, # 목록에서는 요약 제외 가능
                        'sort_timestamp': sort_timestamp # 정렬용 임시 키
                    })
                else:
                     print(f"DEBUG: Skipping item with key {storage_key} due to unexpected source: {source}")

            except Exception as e:
                # 개별 항목 처리 중 오류 발생 시 로깅하고 계속 진행
                print(f"🚨 User 메모리 항목 처리 오류 (UID: {uploader_uid}, Key: {storage_key}): {e}")
                traceback.print_exc()
        # --- ▲▲▲ 인증된 사용자의 데이터만 조회 종료 ▲▲▲ ---

        # 시간순 정렬 (최신순) - sort_timestamp 사용
        # datetime.min 은 타임스탬프 없는 항목을 맨 뒤로 보냄 (None 대신 사용)
        all_summaries_data.sort(key=lambda x: x.get('sort_timestamp') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # 정렬에 사용된 timestamp 제거 후 최종 데이터 생성
        final_data_to_send = []
        for item in all_summaries_data:
            item.pop('sort_timestamp', None) # sort_timestamp 키 제거
            final_data_to_send.append(item)

        print(f"--- '/api/summaries' (User Specific Memory) 처리 완료, 사용자 {uploader_uid} ({uploader_email})에게 {len(final_data_to_send)}개 항목 반환 ---")
        return jsonify(final_data_to_send)

    except Exception as e:
        # 전체 로직에서 예외 발생 시
        print(f"🚨 요약 목록(User Specific Memory) 생성 오류: {e}")
        traceback.print_exc()
        return jsonify({"error": "목록 생성 실패"}), 500


# ==============================================================================
# === /api/memory/<storage_key> 수정: 사용자 데이터 접근 시 인증 및 소유권 확인 ===
# ==============================================================================

@app.route("/api/memory/<string:storage_key>", methods=['GET'])
def get_memory_data(storage_key):
    """주어진 키로 메모리에서 데이터 검색 (User Memory는 소유권 확인)"""
    print(f"--- '/api/memory/{storage_key}' 요청 처리 시작 ---")
    print(f"🔍 요청받은 storage_key: '{storage_key}'") # <<< 디버깅용 로그 추가: 어떤 키가 요청되었는지 확인
    # print(f"🔍 요청 헤더: {request.headers}") # <<< 디버깅용 로그 추가: Authorization 헤더 및 기타 정보 확인 필요시 사용
    uploader_uid = None # 인증된 사용자의 UID

    # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증 필수) ▼▼▼ ---
    # 이 API는 사용자 데이터 접근 가능성이 있으므로 인증을 먼저 수행
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        print("🚨 /api/memory: Authorization 헤더가 없거나 Bearer 토큰이 아닙니다. 인증 실패.")
        # 사용자 데이터가 아닐 수도 있으므로, 바로 401을 반환할지, 아니면 일단 진행하고
        # 사용자 데이터 접근 시에만 401을 반환할지 결정 필요.
        # 현재 코드는 인증 없이도 Admin Memory를 확인할 수 있도록 진행합니다.
        print("ℹ️ /api/memory: 인증 토큰 없음. 사용자 데이터 접근 불가 상태로 진행.")
        pass # 토큰 없이 진행 시도 (User Memory 접근 불가)

    else:
        id_token = auth_header.split('Bearer ')[1]
        try:
            # ID 토큰 검증 (Firebase Admin SDK 사용)
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid']
            print(f"ℹ️ /api/memory 요청 사용자 UID (ID Token): {uploader_uid}")
        except auth.InvalidIdTokenError as e:
            # 유효하지 않은 토큰은 401 반환
            print(f"🚨 /api/memory: 유효하지 않은 ID 토큰: {e}")
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e:
            # 기타 검증 오류 시 500 반환
            print(f"🚨 /api/memory: 토큰 검증 오류: {e}")
            traceback.print_exc() # 서버 측에서 자세한 오류 확인
            return jsonify({"error": "토큰 검증 중 서버 오류 발생"}), 500
    # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 ▲▲▲ ---

    data_item = None
    found_in = None

    try:
        # --- ▼▼▼ User Memory 확인 (인증된 사용자의 데이터인지 확인) ▼▼▼ ---
        if uploader_uid: # 인증된 사용자만 자신의 데이터 접근 가능
            print(f"🔍 사용자 UID: {uploader_uid}가 확인되었습니다. User Memory를 확인합니다.") # <<< 디버깅용 로그 추가
            if uploader_uid in user_memory_storage:
                 print(f"🔍 user_memory_storage에 사용자 UID '{uploader_uid}' 키가 존재합니다.") # <<< 디버깅용 로그 추가
                 if storage_key in user_memory_storage[uploader_uid]:
                     # 키가 해당 사용자의 데이터에 존재함
                     print(f"✅ Key '{storage_key}'를 User Memory for UID '{uploader_uid}'에서 찾았습니다.") # <<< 디버깅용 로그 수정/추가
                     data_item = user_memory_storage[uploader_uid][storage_key]
                     found_in = "User"
                 else:
                     # 사용자는 인증되었으나 해당 키가 사용자 데이터에 없음
                     print(f"⚠️ Key '{storage_key}'는 User Memory for UID '{uploader_uid}'에 없습니다.") # <<< 디버깅용 로그 추가
            else:
                # 사용자는 인증되었으나 user_memory_storage에 해당 UID 키 자체가 없음 (아직 데이터 저장 안 됐거나 UID 문제)
                print(f"⚠️ user_memory_storage에 사용자 UID '{uploader_uid}'에 해당하는 데이터 저장소가 없습니다.") # <<< 디버깅용 로그 추가

        # --- ▲▲▲ User Memory 확인 종료 ▲▲▲ ---


        # --- ▼▼▼ Admin Memory 확인 (User Memory에서 찾지 못했거나, 인증되지 않은 경우) ▼▼▼ ---
        # User Memory에서 데이터를 찾지 못했을 경우 (data_item이 None일 경우) Admin Memory를 확인합니다.
        if data_item is None:
             print(f"🔍 User Memory에서 Key '{storage_key}'를 찾지 못했거나 인증되지 않았습니다. Admin Memory를 확인합니다.") # <<< 디버깅용 로그 추가
             if storage_key in admin_memory_storage:
                 print(f"✅ Key '{storage_key}'를 Admin Memory에서 찾았습니다.") # <<< 디버깅용 로그 추가
                 data_item = admin_memory_storage[storage_key]
                 found_in = "Admin"
                 # TODO: 관리자 역할(Role) 기반 접근 제어 로직 추가 고려
             else:
                 print(f"⚠️ Key '{storage_key}'는 Admin Memory에도 없습니다.") # <<< 디버깅용 로그 추가
        # --- ▲▲▲ Admin Memory 확인 종료 ▲▲▲ ---


        # --- ▼▼▼ 결과 처리 ▼▼▼ ---
        if data_item:
            # 데이터를 찾았을 경우
            data = data_item.copy() # 원본 수정을 방지하기 위해 복사본 사용

            # 민감 정보나 불필요한 대용량 데이터 제거 (예: files_content)
            # 필요한 경우 더 많은 필드를 제거할 수 있습니다.
            if 'files_content' in data:
                 print(f"ℹ️ 응답 데이터에서 'files_content' 필드를 제거합니다 (Key: '{storage_key}').") # <<< 디버깅용 로그 추가
                 data.pop('files_content', None)

            # 응답 데이터에 포함해서는 안 되는 민감 정보 필드가 있다면 추가 제거
            # 예: data.pop('internal_notes', None)

            print(f"✅ Key '{storage_key}'에 대한 데이터를 {found_in} Memory에서 성공적으로 조회했습니다.") # <<< 최종 성공 로그
            return jsonify(data)
        else:
            # 모든 저장소에서 키를 찾지 못함
            print(f"⚠️ 최종 결과: Key '{storage_key}'를 어떤 메모리 저장소에서도 찾을 수 없습니다.") # <<< 최종 실패 로그
            return jsonify({"error": "요청하신 데이터를 찾을 수 없습니다."}), 404
        # --- ▲▲▲ 결과 처리 끝 ▲▲▲ ---

    except Exception as e:
        # 데이터 검색 또는 처리 중 예외 발생
        print(f"🚨 메모리 데이터 조회 중 서버 오류 발생 (Key: {storage_key}, User: {uploader_uid}): {e}")
        traceback.print_exc() # 서버 콘솔에 전체 스택 트레이스 출력
        return jsonify({"error": "데이터 조회 중 서버 오류가 발생했습니다."}), 500

    except Exception as e:
        # 데이터 검색 또는 처리 중 예외 발생
        print(f"🚨 메모리 데이터 조회 오류 (Key: {storage_key}, User: {uploader_uid}): {e}")
        traceback.print_exc()
        return jsonify({"error": "데이터 조회 중 서버 오류 발생"}), 500
    


    # Note: The client-side code expects the returned data to be an object containing summary, original, metadata etc.
    # Adding 'requester_email' at the top level of the returned 'data' object maintains this structure.
@app.route("/api/debug/memory")
def debug_memory_contents():
    """User 및 Admin 메모리 저장소 전체 내용을 JSON으로 반환 (디버깅용)."""
    print("--- DEBUG: /api/debug/memory 요청 받음 ---")
    try:
        # 바로 jsonify하면 bytes 때문에 오류 발생 가능성 있음
        # 간단한 정보만 보여주거나, bytes는 base64 인코딩 필요
        def make_serializable(data):
             serializable_data = {}
             for key, value in data.items():
                  item_copy = value.copy()
                  # files_content는 제외하거나 다른 방식으로 표현
                  item_copy.pop('files_content', None)
                  serializable_data[key] = item_copy
             return serializable_data

        return jsonify({
            "user_storage_overview": make_serializable(user_memory_storage),
            "admin_storage_overview": make_serializable(admin_memory_storage)
        })
    except Exception as e:
        print(f"🚨 ERROR converting memory storage to JSON: {e}")
        return jsonify({"error": "Failed to serialize memory content", "detail": str(e)}), 500


@app.route("/api/admin_summaries")
def list_admin_summaries():
    """
    관리자 메모리에 저장된 분석/요약 내용과 메타데이터 목록 반환.
    (ID 토큰 인증 필요)
    """
    id_token = None
    uploader_uid = None # 요청을 보낸 사용자의 UID (로깅/감사 목적)

    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]

        if not id_token:
            print("🚨 /api/admin_summaries: Authorization 헤더 없거나 Bearer 토큰 아님.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        try:
            # ID 토큰 검증 (auth 객체가 초기화되어 있어야 함)
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # <<< 요청 사용자 UID 획득!
            print(f"ℹ️ /api/admin_summaries 요청 사용자 UID (ID Token): {uploader_uid}")

            # --- (선택 사항) 추가적인 접근 권한 확인 로직 ---
            # 예를 들어, 특정 사용자 그룹만 이 API를 호출할 수 있게 하려면 여기서 확인
            # if not check_permission_for_admin_api(uploader_uid):
            #     print(f"🚨 /api/admin_summaries: 사용자 {uploader_uid} 접근 권한 없음.")
            #     return jsonify({"error": "접근 권한이 없습니다."}), 403

        except auth.InvalidIdTokenError as e:
            print(f"🚨 /api/admin_summaries: 유효하지 않은 ID 토큰: {e}")
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e: # 토큰 검증 또는 권한 확인 중 다른 오류
            print(f"🚨 /api/admin_summaries: 토큰 검증/권한 확인 오류: {e}")
            traceback.print_exc()
            return jsonify({"error": "토큰 검증/권한 확인 중 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 (인증) ▲▲▲ ---

        # --- 인증 통과 후 기존 로직 수행 ---
        all_admin_data = []
        print(f"--- '/api/admin_summaries' (Admin Memory) 데이터 조회 시작 (요청자: {uploader_uid}) ---")

        # --- ▼▼▼ admin_memory_storage 순회 (기존과 동일) ▼▼▼ ---
        for storage_key, data_item in admin_memory_storage.items():
            try:
                metadata = data_item.get('metadata', {})
                timestamp_iso = data_item.get('timestamp')
                key_topic = metadata.get('key', 'N/A')
                current_status = data_item.get('processing_status', '수임') # 기본값 '수임'
                name = metadata.get('name', 'N/A')
                phone = metadata.get('phone', 'N/A')
                region = metadata.get('region', 'N/A')

                formatted_date = "N/A"; sort_timestamp = None
                if timestamp_iso:
                    try:
                        dt_object = datetime.fromisoformat(timestamp_iso)
                        # 시간대 정보가 없는 naive datetime일 경우, 비교를 위해 UTC 등으로 통일
                        if dt_object.tzinfo is None:
                             dt_object = dt_object.replace(tzinfo=timezone.utc) # UTC로 가정
                        formatted_date = dt_object.strftime('%Y-%m-%d %H:%M:%S') # 형식 유지
                        sort_timestamp = dt_object # 정렬용 datetime 객체
                    except ValueError:
                         formatted_date = timestamp_iso # ISO 형식이 아니면 그대로
                         sort_timestamp = datetime.min.replace(tzinfo=timezone.utc) # 정렬 위해 최소값 사용

                admin_info = {
                    'storage_key': storage_key,
                    'name': name,
                    'phone': phone,
                    'region': region,
                    'date_created': formatted_date, # YYYY-MM-DD HH:MM:SS 형식
                    'status': current_status,
                    'key_topic': key_topic,       # 프론트엔드 필터링/표시용
                    'sort_timestamp': sort_timestamp # 정렬용 임시 필드
                 }
                all_admin_data.append(admin_info)

            except Exception as e: print(f"🚨 Admin 메모리 항목 처리 오류 ({storage_key}): {e}"); traceback.print_exc()
        # --- ▲▲▲ admin_memory_storage 순회 종료 ▲▲▲ ---

        # 시간순 정렬 (최신순) - timezone-aware datetime으로 비교
        all_admin_data.sort(key=lambda x: x.get('sort_timestamp') or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # 정렬용 키 제거 후 최종 리스트 생성
        final_data_to_send = []
        for item in all_admin_data:
             item_copy = item.copy()
             if 'sort_timestamp' in item_copy:
                 del item_copy['sort_timestamp']
             final_data_to_send.append(item_copy)

        print(f"--- '/api/admin_summaries' (Admin Memory) 처리 완료, {len(final_data_to_send)}개 항목 반환 (요청자: {uploader_uid}) ---")
        return jsonify(final_data_to_send)

    except Exception as e: # 전체 try 블록에 대한 예외 처리
        print(f"🚨 관리자 목록(Admin Memory) 생성 중 외부 오류: {e}")
        traceback.print_exc()
        return jsonify({"error":"관리자 목록 생성 실패"}), 500





if __name__ == '__main__':
    print("🚀 Flask 서버 시작 중...")
    app.run(host='0.0.0.0', port=8000, debug=False)
