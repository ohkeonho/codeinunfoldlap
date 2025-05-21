# api/routes.py
from flask import Blueprint, request, jsonify,send_file
import zipfile
from firebase_admin import auth
import traceback
import os
import tempfile
import sys
from werkzeug.utils import secure_filename
from datetime import date, datetime, timezone
import mimetypes
from io import BytesIO
# --- 분리된 모듈에서 필요한 컴포넌트 임포트 ---
from config import PYDUB_AVAILABLE, AudioSegment ,ADMIN_EMAILS# AudioSegment는 Mock 또는 실제 클래스
from storage import user_memory_storage, admin_memory_storage
from clients import ClovaSpeechClient
from utils import (
    summarize_text_with_gemini, summarize_with_context,
    extract_text_from_file, find_previous_summary_content,
    _create_summary_list, sanitize_filename
)

# Blueprint 인스턴스 생성
api_bp = Blueprint('api', __name__)
print("--- [API Routes] Blueprint created ---")

# ==============================
# ===      API 라우트 정의     ===
# ==============================

@api_bp.route("/logout", methods=['POST'])
def logout_user():
    """사용자 로그아웃 처리"""
    uploader_uid = None
    try:
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "인증 토큰 필요"}), 401
        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid']
            print(f"ℹ️ /api/logout 요청 UID: {uploader_uid}")
        except Exception as auth_err:
             print(f"⚠️ /api/logout: 토큰 검증 실패: {auth_err}")
             return jsonify({"message": "토큰 검증 실패, 클라이언트 로그아웃 진행"}), 200
        try:
            auth.revoke_refresh_tokens(uploader_uid)
            print(f"✅ UID {uploader_uid} 리프레시 토큰 무효화 성공.")
            return jsonify({"message": "로그아웃 성공 (토큰 무효화)."}), 200
        except Exception as revoke_err:
            print(f"🚨 /api/logout: 리프레시 토큰 무효화 실패: {revoke_err}")
            return jsonify({"error": "로그아웃 서버 오류", "detail": str(revoke_err)}), 500
    except Exception as e:
        print(f"🚨 /api/logout: 예외 발생: {e}")
        traceback.print_exc()
        return jsonify({"error": "로그아웃 중 오류 발생"}), 500

@api_bp.route("/upload", methods=['POST'])
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
        # 요청에 따라 임시 오디오 파일을 삭제하지 않도록 수정
        # if temp_file_path and os.path.exists(temp_file_path):
        #    try: os.remove(temp_file_path); print(f"🧹 임시 오디오 파일 삭제됨: {temp_file_path}")
        #    except OSError as e: print(f"🚨 임시 오디오 파일 삭제 실패: {e}")
        # temp_file_path = None # 경로 변수 초기화 (파일은 유지되므로 변수 초기화는 선택 사항)

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
                'audio_temp_path': temp_file_path, # <--- 임시 파일 경로 저장
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
                'user_email': uploader_email,     # 프론트에서 즉시 필요시 반환
                'audio_temp_path': temp_file_path # <--- 임시 파일 경로 반환 (디버그/확인용)
            }), 200
        else:
            # Clova API 실패 처리
            print(f"🚨 Clova API 실패 ({res.status_code}). 응답: {clova_response_text[:200]}...")
            return jsonify({'error': 'Clova 음성 인식 실패', 'detail': clova_response_text}), res.status_code

    except Exception as e:
        # --- 전체 예외 처리 ---
        print(f"🚨 예외 발생 (upload): {e}"); print(traceback.format_exc())

        # 요청에 따라 임시 오디오 파일은 오류 발생 시에도 삭제하지 않도록 수정
        # if temp_file_path and os.path.exists(temp_file_path):
        #    try: os.remove(temp_file_path); print(f"🧹 오류로 임시 오디오 삭제: {temp_file_path}")
        #    except OSError as e_rem: print(f"🚨 오류 시 임시 오디오 삭제 실패: {e_rem}")

        # --- ▼▼▼ 중첩 구조 메모리 정리 ▼▼▼ ---
        # 오류 발생 시 메모리에 불완전하게 저장된 데이터가 있다면 정리
        if uploader_uid and storage_key and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
            try:
                del user_memory_storage[uploader_uid][storage_key]
                print(f"🧹 오류로 User 메모리 데이터 삭제 (UID: {uploader_uid}, Key: {storage_key})")
                # 해당 사용자 데이터가 모두 삭제되어 폴더가 비었는지 확인 후 폴더 자체 삭제 (선택적)
                if not user_memory_storage[uploader_uid]:
                    del user_memory_storage[uploader_uid]
                    print(f"🧹 오류로 빈 사용자 폴더 삭제됨 (UID: {uploader_uid})")
            except KeyError:
                 print(f"🧹 오류 발생 시 메모리 정리 중 Key 이미 없음 (UID: {uploader_uid}, Key: {storage_key})")
        # --- ▲▲▲ 중첩 구조 메모리 정리 ▲▲▲ ---

        return jsonify({'error': '서버 내부 오류', 'exception': str(e)}), 500

@api_bp.route("/record", methods=['POST'])
def record_audio():
    """웹 녹음 처리 (WebM->WAV->STT->요약-> user_memory_storage 저장) + ID 토큰 인증 (필수)"""
    global user_memory_storage
    temp_webm_path, temp_wav_path, storage_key = None, None, None
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
        # PYDUB_AVAILABLE 이 정의되어 있고 False인지 확인
        if 'PYDUB_AVAILABLE' in globals() and not PYDUB_AVAILABLE:
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
            # 변환 실패 시 관련 임시 파일 정리 로직 제거 (요청에 따라 파일을 남김)
            # if temp_webm_path and os.path.exists(temp_webm_path):
            #     try: os.remove(temp_webm_path); print(f"🧹 (변환실패) 임시 WebM 삭제: {temp_webm_path}")
            #     except OSError as e_rem: print(f"🚨 (변환실패) 임시 WebM 삭제 실패: {e_rem}")
            return jsonify({'error': '오디오 파일 변환 실패', 'detail': str(e)}), 500
        finally:
            # 변환 성공/실패 여부와 관계없이 원본 임시 WebM은 삭제 -> 요청에 따라 삭제 로직 제거
            # if temp_webm_path and os.path.exists(temp_webm_path):
            #     try: os.remove(temp_webm_path); print(f"🧹 원본 임시 WebM 삭제: {temp_webm_path}")
            #     except OSError as e: print(f"🚨 임시 WebM 삭제 실패: {e}")
            # temp_webm_path = None # 경로 변수 초기화 (파일은 유지되므로 변수 초기화는 선택 사항)
            pass # 파일 삭제 로직을 제거했으므로 finally에서 할 일 없음

        # 변환된 WAV 파일 존재 확인 (삭제 로직을 제거했으므로 이 코드는 필요 없어짐)
        # if not temp_wav_path or not os.path.exists(temp_wav_path):
        #     # 이 경우는 위의 finally 블록 때문에 발생하기 어려우나 방어적으로 추가
        #     print("🚨 /record: WAV 변환 후 파일이 존재하지 않음.")
        #     return jsonify({'error': 'WAV 변환 알 수 없는 오류'}), 500

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
        # 요청에 따라 임시 WAV 파일을 삭제하지 않도록 수정
        # if temp_wav_path and os.path.exists(temp_wav_path):
        #    try: os.remove(temp_wav_path); print(f"🧹 임시 WAV 삭제: {temp_wav_path}")
        #    except OSError as e: print(f"🚨 임시 WAV 삭제 실패: {e}")
        # temp_wav_path = None # 경로 변수 초기화 (파일은 유지되므로 변수 초기화는 선택 사항)

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
                'audio_temp_webm_path': temp_webm_path, # <--- 임시 WebM 파일 경로 저장
                'audio_temp_wav_path': temp_wav_path,   # <--- 임시 WAV 파일 경로 저장
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
                'user_email': uploader_email,
                'audio_temp_webm_path': temp_webm_path, # <--- 임시 파일 경로 반환 (디버그/확인용)
                'audio_temp_wav_path': temp_wav_path    # <--- 임시 파일 경로 반환 (디버그/확인용)
            }), 200
        else:
            # Clova API 실패 처리
            print(f"🚨 Clova API 실패 ({res.status_code}, 녹음). 응답: {clova_response_text[:200]}...")
            return jsonify({'error': 'Clova 음성 인식 실패', 'detail': clova_response_text}), res.status_code

    # --- 전체 예외 처리 ---
    except Exception as e:
        print(f"🚨 예외 발생 (record): {e}"); print(traceback.format_exc())

        # 임시 파일 정리 (WebM, WAV) - 오류 발생 시에도 삭제하지 않도록 수정
        # if temp_webm_path and os.path.exists(temp_webm_path):
        #     try: os.remove(temp_webm_path); print(f"🧹 오류로 임시 WebM 삭제: {temp_webm_path}")
        #     except OSError as e_rem: print(f"🚨 오류 시 임시 WebM 삭제 실패: {e_rem}")
        # if temp_wav_path and os.path.exists(temp_wav_path):
        #     try: os.remove(temp_wav_path); print(f"🧹 오류로 임시 WAV 삭제: {temp_wav_path}")
        #     except OSError as e_rem: print(f"🚨 오류 시 임시 WAV 삭제 실패: {e_rem}")
        pass # 파일 삭제 로직을 제거했으므로 예외 처리에서 할 일 없음

        # --- ▼▼▼ 중첩 구조 메모리 정리 (/upload와 동일 방식) ▼▼▼ ---
        # 오류 발생 시 메모리에 불완전하게 저장된 데이터가 있다면 정리
        if uploader_uid and storage_key and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
            try:
                del user_memory_storage[uploader_uid][storage_key]
                print(f"🧹 오류로 User 메모리 데이터 삭제 (UID: {uploader_uid}, Key: {storage_key}, Source: /record)")
                # 해당 사용자 데이터가 모두 삭제되어 폴더가 비었는지 확인 후 폴더 자체 삭제 (선택적)
                if not user_memory_storage[uploader_uid]:
                    del user_memory_storage[uploader_uid]
                    print(f"🧹 빈 사용자 폴더 삭제됨 (UID: {uploader_uid}, Source: /record)")
            except KeyError:
                 print(f"🧹 오류 발생 시 메모리 정리 중 Key 이미 없음 (UID: {uploader_uid}, Key: {storage_key}, Source: /record)")
        # --- ▲▲▲ 중첩 구조 메모리 정리 ▲▲▲ ---

        return jsonify({'error': '서버 내부 오류', 'exception': str(e)}), 500

@api_bp.route("/admin/upload", methods=['POST'])
def admin_upload_route_logic():
    """
    관리 인터페이스 파일 업로드 처리. 인증 후 파일 분석.
    PDF/JPG 문서는 ZIP으로 압축하여 저장 정보 관리.
    """
    global user_memory_storage

    # 초기 변수 설정
    storage_key = None
    uploader_uid = None
    uploader_email = '업로더 이메일 정보 없음'
    client_email_target = None
    target_name = None
    target_phone = None
    target_region = None
    key_topic = None
    success_flag = False
    processed_files_full_metadata = [] # 최종 파일 메타데이터 리스트
    temp_files_to_clean = [] # finally에서 '상태 확인'할 임시 파일 경로 리스트
    files_to_zip = [] # ZIP으로 묶을 파일 정보 (temp_path, original_filename)
    other_document_files_metadata = [] # ZIP에 포함되지 않는 문서 파일 메타데이터
    document_details_for_ocr = [] # 모든 문서 파일의 OCR 처리용 정보 (추출 후 ZIP 처리)
    temp_files_zipped_and_removed = set() # ZIP에 포함 후 즉시 삭제된 파일 경로 추적용

    print(f"--- '/admin/upload' 요청 처리 시작 ---")

    try:
        # --- 인증 및 업로더 정보 획득 ---
        # (기존 코드와 동일)
        auth_header = request.headers.get('Authorization')
        id_token = None
        if auth_header and auth_header.startswith('Bearer '): id_token = auth_header.split('Bearer ')[1]
        if not id_token: return jsonify({"error": "인증 토큰 필요"}), 401
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid']
            uploader_email = decoded_token.get('email', uploader_email)
            print(f"ℹ️ /admin/upload 요청 수행자 UID: {uploader_uid}, Email: {uploader_email}")
        except Exception as e:
            print(f"🚨 /admin/upload: 토큰 검증 오류: {e}")
            return jsonify({"error": "토큰 검증 오류", "detail": str(e)}), 401

        # --- 1. 폼 데이터 및 파일 확인 ---
        # (기존 코드와 동일)
        client_email_target = request.form.get('clientEmail', '').strip()
        target_name = request.form.get('name', '').strip()
        target_phone = request.form.get('phone', '').strip()
        target_region = request.form.get('region', '').strip()
        key_topic = request.form.get('key', '').strip()

        if not key_topic: return jsonify({'error': '필수 입력 누락: 문서 종류(key)'}), 400
        if 'audioFile' not in request.files or not request.files['audioFile'].filename:
             return jsonify({'error': '오디오 파일(audioFile) 필요'}), 400
        audio_file = request.files['audioFile']
        document_files = request.files.getlist('documentFiles')
        if not document_files or not any(f.filename for f in document_files):
             return jsonify({'error': '하나 이상의 문서 파일(documentFiles) 필요'}), 400

        # --- 2. Storage Key 생성 ---
        # (기존 코드와 동일)
        safe_name = sanitize_filename(target_name)
        safe_phone = sanitize_filename(target_phone)
        safe_region = sanitize_filename(target_region)
        safe_client_email_for_key = sanitize_filename(client_email_target)
        safe_uploader_email_for_key = sanitize_filename(uploader_email)
        current_datetime_str = datetime.now().strftime('%Y%m%d_%H%M%S%f')
        storage_key = f"{safe_name}_{safe_phone}_{safe_region}_{safe_client_email_for_key}_{current_datetime_str}_admin_{sanitize_filename(key_topic)}"
        print(f"ℹ️ 생성된 Storage Key (2차 키): {storage_key} (Topic: {key_topic}, Target Email: {client_email_target}, Uploader: {uploader_email})")


        # --- 3. 파일 임시 저장 및 메타데이터 기록 (오디오) ---
        # (기존 코드와 동일)
        temp_audio_path = None
        audio_original_filename = secure_filename(audio_file.filename)
        audio_processed_filename = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(audio_original_filename)[1]) as temp_audio:
                audio_file.save(temp_audio.name)
                temp_audio_path = temp_audio.name
                temp_files_to_clean.append(temp_audio_path) # 정리 목록에 추가
                audio_processed_filename = os.path.basename(temp_audio_path)
                audio_size = os.path.getsize(temp_audio_path)
                audio_type, _ = mimetypes.guess_type(temp_audio_path)
                if not audio_type: audio_type = 'application/octet-stream'

                # 오디오 파일 메타데이터 저장
                processed_files_full_metadata.append({
                    'type': 'audio',
                    'original_filename': audio_original_filename,
                    'processed_filename': audio_processed_filename,
                    'temp_path': temp_audio_path,
                    'size': audio_size,
                    'mime_type': audio_type
                })
                print(f"✅ [AdminUpload] 오디오 임시 저장: {temp_audio_path} ({audio_size} bytes)")
        except Exception as audio_save_err:
            print(f"🚨 [AdminUpload] 오디오 파일 저장 오류: {audio_save_err}")
            # 필요 시 여기서 중단 결정
            # return jsonify({"error": f"오디오 파일 저장 오류: {audio_save_err}"}), 500


        # --- 4. 문서 파일 임시 저장 & ★ OCR 정보 수집 ★ ---
        print(f"⏳ [AdminUpload] {len(document_files)}개 문서 파일 임시 저장 및 OCR 대상 분류 시작...")
        for i, doc_file in enumerate(document_files):
            if doc_file and doc_file.filename:
                original_doc_filename = secure_filename(doc_file.filename)
                doc_processed_filename = None
                doc_temp_path = None
                try:
                    # 모든 문서 파일을 일단 임시 저장
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(original_doc_filename)[1]) as temp_doc:
                         doc_file.save(temp_doc.name)
                         doc_temp_path = temp_doc.name
                         # ★ 중요: 아직 정리 목록(temp_files_to_clean)에 추가하지 않음. ZIP 처리 후 결정
                         doc_processed_filename = os.path.basename(doc_temp_path)
                         doc_size = os.path.getsize(doc_temp_path)
                         doc_type, _ = mimetypes.guess_type(doc_temp_path)
                         if not doc_type: doc_type = 'application/octet-stream'

                         print(f"✅ [AdminUpload] 문서 임시 저장 ({i+1}): {original_doc_filename} -> {doc_temp_path} ({doc_size} bytes)")

                         # ★ 모든 문서에 대해 OCR/텍스트 추출 정보 추가 ★
                         document_details_for_ocr.append({
                             'original_filename': original_doc_filename,
                             'temp_path': doc_temp_path,
                             'processed_filename': doc_processed_filename, # 필요 시 사용
                             'size': doc_size,                            # 필요 시 사용
                             'mime_type': doc_type                         # 필요 시 사용
                         })

                         # ★ PDF/JPG 파일 분류 ★
                         file_ext = os.path.splitext(original_doc_filename)[1].lower()
                         # MIME 타입으로도 확인 가능: if doc_type in ['application/pdf', 'image/jpeg']:
                         if file_ext in ['.pdf', '.jpg', '.jpeg']:
                             files_to_zip.append({'temp_path': doc_temp_path, 'original_filename': original_doc_filename})
                             print(f"  ->  분류: ZIP 대상 ({original_doc_filename})")
                         else:
                             # PDF/JPG가 아닌 파일은 메타데이터를 바로 other_document_files_metadata 에 추가
                             other_document_files_metadata.append({
                                 'type': 'document',
                                 'original_filename': original_doc_filename,
                                 'processed_filename': doc_processed_filename,
                                 'temp_path': doc_temp_path,
                                 'size': doc_size,
                                 'mime_type': doc_type
                             })
                             temp_files_to_clean.append(doc_temp_path) # 정리 목록에 추가
                             print(f"  -> 분류: 개별 유지 대상 ({original_doc_filename})")

                except Exception as doc_save_err:
                    print(f"🚨 [AdminUpload] 문서 '{original_doc_filename}' 임시 저장 오류: {doc_save_err}")
                    # 오류 발생 시 해당 파일 처리 건너뛰기 또는 전체 중단 등 결정

        # --- 5. Clova STT ---
        # (기존 코드와 동일 - 오디오 처리 결과 사용)
        transcribed_text = "[STT 결과 없음]"
        if temp_audio_path and os.path.exists(temp_audio_path):
            print(f"⏳ [AdminUpload] Clova STT 요청 시작 (파일: {os.path.basename(temp_audio_path)})...")
            try:
                clova_client = ClovaSpeechClient()
                res = clova_client.req_upload(file=temp_audio_path, completion='sync', diarization=True)
                print(f"✅ [AdminUpload] Clova 상태코드: {res.status_code}")
                if res.status_code == 200:
                    result_data = res.json()
                    if 'segments' in result_data and result_data['segments']:
                        texts_by_speaker = [f"화자 {s.get('speaker',{}).get('label','?')}: {s.get('text','')}" for s in result_data['segments']]
                        transcribed_text = "\n".join(texts_by_speaker)
                    elif 'text' in result_data: transcribed_text = result_data.get('text','변환된 텍스트 없음')
                    else: transcribed_text = 'Clova 응답에 텍스트 데이터 없음'
                    print(f"✅ [AdminUpload] Clova STT 결과 처리 완료")
                else:
                    transcribed_text = f"[Clova STT 실패: {res.status_code}, {res.text}]"; print(f"🚨 [AdminUpload] Clova STT 실패")
            except Exception as clova_err:
                transcribed_text = f"[Clova API 오류: {clova_err}]"; print(f"🚨 [AdminUpload] Clova API 오류")
        else: print("⚠️ [AdminUpload] 오디오 파일 처리 안됨, STT 건너김.")


        # --- 6. 문서 텍스트 추출 (OCR 등) ---
        # ★ 이제 document_details_for_ocr 에는 모든 문서 정보가 들어있음 ★
        all_document_text_parts = []
        print(f"⏳ [AdminUpload] {len(document_details_for_ocr)}개 문서 텍스트 추출 시작...")
        ocr_error_flag = False
        for doc_detail in document_details_for_ocr:
            extracted_text = "[문서 텍스트 추출 실패]"
            doc_temp_path = doc_detail.get('temp_path')
            original_filename = doc_detail.get('original_filename')
            if doc_temp_path and os.path.exists(doc_temp_path) and original_filename:
                try:
                    # ★ 추출 함수 호출은 동일 ★
                    extracted_text = extract_text_from_file(original_filename=original_filename, file_path=doc_temp_path)
                    print(f"✅ [AdminUpload] 문서 '{original_filename}' 텍스트 추출 완료 (추후 ZIP 포함 여부와 별개)")
                except Exception as ocr_err:
                    print(f"🚨 [AdminUpload] 문서 '{original_filename}' 추출 오류: {ocr_err}")
                    ocr_error_flag = True # 추출 실패 플래그
            else:
                print(f"⚠️ [AdminUpload] 문서 추출 건너김: 임시 경로/파일명 누락 또는 파일 없음 ({original_filename})")
                ocr_error_flag = True # 추출 실패 플래그 (파일 자체가 문제인 경우)

            # ★ 추출된 텍스트 저장 (성공/실패 메시지 포함) ★
            all_document_text_parts.append(f"--- 문서 시작: {original_filename} ---\n{extracted_text}\n--- 문서 끝: {original_filename} ---")


        # --- 7. ★ PDF/JPG 파일 ZIP 압축 ★ ---
        zip_temp_path = None
        if files_to_zip: # ZIP할 파일이 있을 경우에만 실행
            print(f"⏳ [AdminUpload] {len(files_to_zip)}개의 PDF/JPG 파일을 ZIP으로 압축 시작...")
            try:
                # 임시 ZIP 파일 생성
                with tempfile.NamedTemporaryFile(delete=False, suffix='.zip', prefix=f"{storage_key}_docs_") as temp_zip:
                    zip_temp_path = temp_zip.name

                # ZIP 파일 쓰기
                with zipfile.ZipFile(zip_temp_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file_info in files_to_zip:
                        # arcname=원본 파일명으로 ZIP 내부에 저장
                        zipf.write(file_info['temp_path'], arcname=file_info['original_filename'])
                        print(f"  -> 압축 추가: {file_info['original_filename']} (from: {file_info['temp_path']})")

                zip_size = os.path.getsize(zip_temp_path)
                zip_original_filename = f"{storage_key}_documents.zip" # ZIP 파일의 대표 이름
                zip_processed_filename = os.path.basename(zip_temp_path)

                # ★ ZIP 파일 메타데이터 생성 ★
                zip_metadata = {
                    'type': 'document_archive', # 타입 구분: 문서 아카이브
                    'original_filename': zip_original_filename,
                    'processed_filename': zip_processed_filename,
                    'temp_path': zip_temp_path,
                    'size': zip_size,
                    'mime_type': 'application/zip',
                    'contained_files': [f['original_filename'] for f in files_to_zip] # 포함된 파일 목록 (선택적)
                }
                # ★ 최종 메타데이터 리스트에 ZIP 정보 추가 ★
                processed_files_full_metadata.append(zip_metadata)
                temp_files_to_clean.append(zip_temp_path) # ZIP 임시 파일도 정리 대상에 추가
                print(f"✅ [AdminUpload] ZIP 파일 생성 완료: {zip_temp_path} ({zip_size} bytes)")

                # (선택적) ZIP에 포함된 원본 임시 파일들 삭제
                print(f"ℹ️ ZIP에 포함된 개별 임시 파일 삭제 시도...")
                for file_info in files_to_zip:
                    try:
                        os.remove(file_info['temp_path'])
                        temp_files_zipped_and_removed.add(file_info['temp_path']) # 삭제된 파일 추적
                        print(f"  -> 임시 파일 삭제됨: {file_info['temp_path']}")
                    except OSError as e_rem_zip:
                        print(f"🚨 ZIP 포함 파일 삭제 오류: {e_rem_zip} (파일: {file_info['temp_path']})")

            except Exception as zip_err:
                print(f"🚨 [AdminUpload] ZIP 파일 생성 중 오류: {zip_err}")
                # ZIP 생성 실패 시, 개별 파일 메타데이터를 대신 사용할지 결정 필요
                # 여기서는 일단 에러 로그만 남기고 진행 (개별 PDF/JPG 정보는 저장 안 됨)
                # 필요하다면 files_to_zip 내용을 other_document_files_metadata 처럼 처리하는 로직 추가

        # ★ ZIP되지 않은 다른 문서 파일들의 메타데이터를 최종 리스트에 추가 ★
        processed_files_full_metadata.extend(other_document_files_metadata)


        # --- 8. 이전 요약 검색 ---
        # (기존 코드와 동일)
        previous_summary_text = find_previous_summary_content(uploader_uid, target_name, target_phone, target_region) or "[이전 요약 없음]"
        print(f"ℹ️ 이전 요약 검색 결과: {'찾음' if previous_summary_text != '[이전 요약 없음]' else '없음'}")


        # --- 9. Gemini 분석 ---
        # (기존 코드와 동일 - 통합된 문서 텍스트 사용)
        gemini_analysis = "[Gemini 분석 실패]"
        print(f"⏳ [AdminUpload] Gemini 분석 시작...")
        combined_document_text = "\n\n".join(all_document_text_parts) # 모든 문서 텍스트 결합
        try:
            gemini_analysis = summarize_with_context(transcribed_text, combined_document_text, key_topic, previous_summary_text)
            print(f"✅ [AdminUpload] Gemini 분석 완료")
        except Exception as gemini_err:
            print(f"🚨 [AdminUpload] Gemini 분석 오류: {gemini_err}")
            gemini_analysis = f"[Gemini 분석 오류: {gemini_err}]"


        # --- 10. 최종 데이터 객체 생성 ---
        # ★ 'uploaded_files_info'에 ZIP 및 개별 파일 정보가 포함된 리스트 사용 ★
        current_timestamp_iso = datetime.now().isoformat()
        data_to_store = {
            'original': transcribed_text,
            'summary': gemini_analysis,
            'files_content': combined_document_text, # OCR 결과 통합본 (텍스트만)
            'source': f'admin_upload_{key_topic}',
            'timestamp': current_timestamp_iso,
            'metadata': {
                'name': target_name, 'phone': target_phone, 'region': target_region,
                'email': client_email_target,
                'key_topic': key_topic,
                # ★★★ 수정된 파일 정보 리스트 저장 ★★★
                'uploaded_files_info': processed_files_full_metadata, # 여기에 ZIP 정보 또는 개별 파일 정보가 들어감
                'uploader_uid': uploader_uid,
                'uploader_email': uploader_email,
            },
            'processing_status': '분석 완료' if not ocr_error_flag and transcribed_text != "[STT 결과 없음]" and not gemini_analysis.startswith("[Gemini 분석") else '분석 중 오류 발생',
            # ZIP 생성 실패 여부도 상태에 반영 가능
        }
        print(f"ℹ️ 저장될 최종 데이터 객체 생성 완료 (상태: {data_to_store['processing_status']})")


        # --- 11. 데이터 저장 ---
        # (기존 코드와 동일)
        primary_key_for_storage = uploader_uid
        if primary_key_for_storage not in user_memory_storage:
            user_memory_storage[primary_key_for_storage] = {}
            print(f"DEBUG: Created new memory space for Primary Key (Uploader UID): {primary_key_for_storage}")

        user_memory_storage[primary_key_for_storage][storage_key] = data_to_store
        print(f"✅ Data successfully saved to user_memory_storage (PK Uploader UID: {primary_key_for_storage}, SK: {storage_key})")
        success_flag = True


        # --- 성공 응답 ---
        # (기존 코드와 동일)
        return jsonify({
            'message': f'{key_topic} 처리 및 저장 완료 (PDF/JPG는 ZIP으로)',
            'storage_key': storage_key,
            'uploader_email': uploader_email,
            'uploader_uid': uploader_uid,
            'client_email': client_email_target,
            # 필요 시 ZIP 파일 정보 등 추가 반환 가능
        }), 200


    except ValueError as ve:
        # (기존 코드와 동일)
        print(f"🚨 입력/파일 처리 오류 (/admin/upload): {ve}")
        return jsonify({'error': f'입력/파일 처리 오류: {str(ve)}'}), 400
    except Exception as e:
        # (기존 코드와 동일 - 롤백 로직 포함)
        print(f"🚨 예외 발생 (/admin/upload): {e}")
        traceback.print_exc()
        if storage_key and not success_flag and uploader_uid and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
            try: del user_memory_storage[uploader_uid][storage_key]; print(f"🧹 오류 발생, 데이터 롤백됨: {storage_key}")
            except Exception as del_err: print(f"🚨 롤백 중 삭제 오류: {del_err}")
        return jsonify({'error': '서버 내부 오류 발생', 'exception': str(e)}), 500

    finally:
        # --- 임시 파일 정리 ---
        # ★ 주석 처리된 삭제 로직 대신, 파일 유지 및 상태 확인 로그만 남김 ★
        # ★ ZIP 처리 후 삭제된 파일은 건너뛰도록 확인 추가 ★
        print("ℹ️ 임시 파일 상태 확인 시작 (삭제 안 함).")
        for path in temp_files_to_clean:
            if path in temp_files_zipped_and_removed: # ZIP 처리 후 이미 삭제된 파일이면 건너뜀
                print(f"  -> 확인 건너뜀 (ZIP 포함 후 삭제됨): {path}")
                continue
            if path and os.path.exists(path):
                try:
                    # os.remove(path); print(f"🧹 임시 파일 삭제: {path}") # <<< 실제 삭제는 주석 처리됨
                    print(f"  -> 임시 파일 유지 확인: {path}") # 유지 로그
                except OSError as e_rem: # 혹시 모를 접근 오류 대비
                    print(f"🚨 임시 파일 상태 확인 중 오류?: {e_rem} (파일: {path})")
            elif path:
                print(f"  -> 임시 파일 경로 확인됨 (파일 없음): {path}")

        print(f"--- '/admin/upload' 요청 처리 완료 ---")



@api_bp.route("/admin/documents/all", methods=['GET'])
def list_all_admin_documents():
    """
    [사용자 전용] 인증된 사용자의 특정 클라이언트에 대한 중요 문서 목록을 통합하여 반환합니다.
    관리자 권한 확인 없이, 로그인한 사용자의 문서만 조회합니다.
    인증 필수. client_identifier 쿼리 파라미터로 클라이언트를 지정합니다.
    """
    id_token = None
    requester_uid = None # 요청자 UID (로그인 사용자)
    requester_email = '이메일 정보 없음' # 요청자 이메일

    # user_memory_storage 전역 변수 사용 명시
    global user_memory_storage
    # auth 객체가 초기화되어 있는지 확인합니다. (Firebase 인증 모듈)
    global auth
    # ADMIN_EMAILS 전역 변수는 이 함수에서 직접적인 권한 확인에 사용되지 않습니다.
    # 하지만 다른 곳에서 사용될 수 있으므로 global 선언은 유지합니다.
    global ADMIN_EMAILS


    if not auth:
        print("🚨 /api/admin/documents/all: Firebase Auth object not available.")
        return jsonify({"error": "Server authentication system error"}), 500

    print(f"--- '/api/admin/documents/all' (사용자 전용) 데이터 조회 요청 처리 시작 ---") # 로그 메시지 업데이트

    try:
        # --- ▼▼▼ ID 토큰 확인 및 요청자 UID, 이메일 얻기 (필수!) ▼▼▼ ---
        # 사용자를 인증하고 해당 사용자의 UID와 이메일을 가져옵니다.
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/admin/documents/all: 인증 토큰 없음.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            # 실제 Firebase Admin SDK의 auth.verify_id_token을 사용하여 토큰 검증
            # 이 부분에서 오류 발생 시 하단의 except Exception 블록으로 이동합니다.
            decoded_token = auth.verify_id_token(id_token)

            requester_uid = decoded_token.get('uid') # 요청자 UID (데이터 필터링의 핵심)
            requester_email = decoded_token.get('email', '이메일 정보 없음') # 요청자 이메일 추출 (로그 및 _create_summary_list에 전달)

            if not requester_uid: # UID는 사용자 데이터 조회를 위해 필수
                 print("🚨 /api/admin/documents/all: 유효 토큰이나 UID 정보 없음.")
                 return jsonify({"error": "인증 토큰에 사용자 정보가 없습니다."}), 401

            # 이메일 정보는 로깅 및 _create_summary_list 함수 내 로직에 사용될 수 있습니다.
            if requester_email == '이메일 정보 없음':
                 print("⚠️ /api/admin/documents/all: 유효 토큰이나 이메일 정보 없음. 로깅/필터링에 제한될 수 있습니다.")
                 # UID가 있으므로 목록 조회 진행은 가능합니다.

            print(f"ℹ️ /api/admin/documents/all 요청 사용자 UID: {requester_uid}, Email: {requester_email}")

            # --- 관리자 권한 확인 로직 제거 (사용자 요구사항 반영) ---
            # 이 엔드포인트는 이제 관리자 전용이 아니므로 관리자 이메일 확인 로직을 삭제합니다.
            # 사용자의 데이터를 조회하는 것은 인증만 되면 가능합니다.
            # ADMIN_EMAILS는 이 함수 내에서 더 이상 접근 제어에 사용되지 않습니다.
            # if requester_email not in ADMIN_EMAILS:
            #      print(f"🚨 /api/admin/documents/all: 관리자 권한 없음. 요청자 이메일: {requester_email}")
            #      return jsonify({"error": "관리자 권한이 필요합니다."}), 403 # 이 부분을 삭제했습니다.

        except Exception as auth_err: # 토큰 검증 또는 디코딩된 토큰에서 정보 추출 중 오류 발생 시
            # 이 예외는 auth.verify_id_token 실패, decoded_token에서 정보 추출 실패 등 다양한 원인으로 발생할 수 있습니다.
            print(f"🚨 /api/admin/documents/all: 토큰 검증 오류: {auth_err}")
            traceback.print_exc() # 서버 콘솔에 상세 오류 출력
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 401 # 인증 실패 시 401 반환

        # --- ▲▲▲ ID 토큰 확인 및 요청자 UID, 이메일 얻기 완료 ▲▲▲ ---


        # --- ▼▼▼ client_identifier 쿼리 파라미터 가져오기 (필수) ▼▼▼ ---
        client_identifier_filter = request.args.get('client_identifier')
        print(f"ℹ️ /api/admin/documents/all 요청 client_identifier 필터: {client_identifier_filter}")

        if not client_identifier_filter:
            print("🚨 /api/admin/documents/all: client_identifier 쿼리 파라미터 누락.")
            return jsonify({"error": "client_identifier 쿼리 파라미터가 필요합니다."}), 400
        # --- ▲▲▲ client_identifier 쿼리 파라미터 가져오기 ▲▲▲ ---


        # --- 인증 및 필수 파라미터 확인 후 로직 수행 (각 토픽별 데이터 필터링 및 통합) ---
        print(f"--- '/api/admin/documents/all' 데이터 필터링 및 통합 시작 (사용자: {requester_uid}, 클라이언트: {client_identifier_filter}) ---")

        # _create_summary_list 호출 전에 해당 사용자 데이터가 있는지 먼저 확인하여 불필요한 탐색을 막습니다.
        user_specific_storage_data = user_memory_storage.get(requester_uid, {})
        if not user_specific_storage_data:
             print(f"ℹ️ 사용자 '{requester_uid}'에 대한 데이터가 user_memory_storage에 없습니다. 빈 목록 반환.")
             return jsonify([]) # 해당 사용자의 데이터가 없으면 빈 목록 반환


        # 통합하여 가져올 문서 토픽 목록 (기존과 동일)
        desired_topics = ["고소장", "보충이유서", "검찰의견서", "합의서", "처벌불원서", "약식명령 의견서", "불기소처분 이의신청서", "기소유예의견서", "변호인 의견서 (공판 준비)", "최종 변론서", "항소이유서", "상고이유서", "내용증명", "조정신청서(소 제기 전)", "소장", "청구취지 및 청구원인 작성", "답변서(피고)", "반소장", "변론준비서면", "조정조서", "집행문 부여 신청서", "강제집행 신청서", "채권압류 및 추심명령 신청서", "부동산 강제경매 신청서"]
        combined_results = []

        # 각 토픽별로 _create_summary_list 호출하고 결과 통합
        # _create_summary_list 함수에 user_memory_storage 전체와 요청자의 UID를 target_uid로 전달
        # _create_summary_list는 내부적으로 target_uid를 보고 해당 사용자의 데이터 내에서만 검색해야 합니다.
        for topic in desired_topics:
            try:
                # _create_summary_list 호출 시 target_uid를 로그인한 사용자의 UID로 지정합니다.
                # 이 호출이 성공적으로 동작하려면 _create_summary_list 함수가 target_uid 인자를 받고
                # 해당 사용자의 데이터 (예: storage_to_search.get(target_uid, {})) 내에서만 검색하도록 수정되어 있어야 합니다.
                topic_data = _create_summary_list(
                    user_memory_storage, # 전체 스토리지 전달 (target_uid 필터링은 _create_summary_list 내부에서)
                    requester_email,     # 요청자 이메일 전달 (로깅 및 _create_summary_list 내부 사용)
                    required_topic=topic,
                    client_identifier=client_identifier_filter,
                    target_uid=requester_uid # <-- 로그인한 사용자의 UID를 target_uid로 전달
                )
                print(f"  - {topic} 항목 {len(topic_data)}개 (클라이언트: {client_identifier_filter}) 조회 완료 (사용자: {requester_uid}).")
                combined_results.extend(topic_data) # 결과 리스트에 추가
            except Exception as topic_filter_err:
                print(f"⚠️ {topic} 목록 (클라이언트: {client_identifier_filter}) 필터링 중 오류 발생: {topic_filter_err}. 해당 토픽 결과는 제외될 수 있습니다 (사용자: {requester_uid}).")
                traceback.print_exc() # 필터링 중 오류 발생 시 상세 정보 출력


        # 필요한 경우, combined_results를 특정 기준으로 정렬 (날짜 최신순)
        # _create_summary_list에서 이미 정렬되지만, 여러 토픽의 결과가 합쳐졌으므로 전체 정렬이 필요합니다.
        try:
            def get_sort_key(item):
                 timestamp_val = item.get('date_created') or item.get('timestamp')
                 if isinstance(timestamp_val, str):
                     try:
                         # ISO 8601 형식 문자열 파싱 (UTC 고려)
                         return datetime.fromisoformat(timestamp_val.replace('Z', '+00:00'))
                     except ValueError:
                         # 파싱 실패 시 최소 시간 반환하여 정렬 순서에 영향 최소화
                         return datetime.min.replace(tzinfo=timezone.utc)
                 # 유효한 시간 정보가 없는 항목은 맨 뒤로
                 return datetime.min.replace(tzinfo=timezone.utc)

            combined_results.sort(key=get_sort_key, reverse=True)
            print(f"--- '/api/admin/documents/all' 결과 목록 날짜 기준으로 최종 정렬 완료 (총 {len(combined_results)}개). ---")

        except Exception as sort_err:
            print(f"⚠️ '/api/admin/documents/all' 결과 목록 정렬 중 오류 발생: {sort_err}")
            traceback.print_exc()
            # 정렬 오류 발생 시, 정렬되지 않은 상태로 결과 반환


        print(f"--- '/api/admin/documents/all' 처리 완료 (사용자: {requester_uid}, 클라이언트: {client_identifier_filter}), 총 {len(combined_results)}개 항목 반환 ---")
        return jsonify(combined_results)

    except Exception as e: # 예상치 못한 서버 내부 오류 (인증 오류 제외)
        print(f"🚨 '/api/admin/documents/all' 통합 문서 목록 생성 중 예상치 못한 서버 오류 (사용자: {requester_uid}, 클라이언트: {client_identifier_filter}): {e}")
        traceback.print_exc() # 서버 콘솔에 전체 스택 트레이스 출력
        return jsonify({"error":"통합 문서 목록 생성 중 서버 오류", "detail": str(e)}), 500

# --- 목록 조회 라우트 ---
# @api_bp.route("/complaints")
# def list_complaints():
#     """고소장 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
#     id_token = None
#     uploader_uid = None # 요청자 UID (로깅용)
#     requester_email = '이메일 정보 없음' # 요청자 이메일

#     # user_memory_storage 전역 변수 사용 명시 ▼▼▼
#     global user_memory_storage

#     # auth 객체가 초기화되어 있는지 확인합니다. (실제 auth 또는 Mock)
#     if not auth:
#         print("🚨 /api/complaints: Firebase Auth object not available.")
#         return jsonify({"error": "Server authentication system error"}), 500

#     try:
#         # --- ▼▼▼ ID 토큰 확인 및 요청자 UID, 이메일 얻기 (필수!) ▼▼▼ ---
#         auth_header = request.headers.get('Authorization')
#         if not auth_header or not auth_header.startswith('Bearer '):
#             print("🚨 /api/complaints: 인증 토큰 없음.")
#             # 목록 조회를 위해 인증 필수
#             return jsonify({"error": "인증 토큰이 필요합니다."}), 401

#         id_token = auth_header.split('Bearer ')[1]
#         try:
#             decoded_token = auth.verify_id_token(id_token) # 토큰 검증
#             uploader_uid = decoded_token.get('uid') # 요청자 UID (get 사용)
#             requester_email = decoded_token.get('email', '이메일 정보 없음') # 요청자 이메일 추출

#             if requester_email == '이메일 정보 없음':
#                  print("🚨 /api/complaints: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
#                  # 필터링을 위해 이메일 필수
#                  return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401 # 또는 403

#             print(f"ℹ️ /api/complaints 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")
#             # 관리자 체크는 _create_summary_list 내부에서 이메일로 수행됩니다.

#         except Exception as auth_err: # 토큰 검증/정보 추출 오류
#             print(f"🚨 /api/complaints: 토큰 검증 오류: {auth_err}")
#             traceback.print_exc()
#             is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
#             error_status_code = 401 if is_invalid_token_error else 500
#             return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500
#         # --- ▲▲▲ ID 토큰 확인 및 요청자 UID, 이메일 얻기 ▲▲▲ ---

#         # --- 인증 통과 후 로직 수행 (데이터 필터링) ---
#         print(f"--- '/api/complaints' 데이터 조회 시작 (요청자: {requester_email}) ---")
#         # user_memory_storage 전체에서 고소장 목록을 가져오되, 요청자의 이메일과 토픽("고소장")으로 필터링 ▼▼▼
#         # _create_summary_list 함수는 다른 곳에 정의되어 있으며, user_memory_storage 구조를 탐색하고 필터링합니다.
#         data = _create_summary_list(user_memory_storage, requester_email, required_topic="고소장") # <--- 조회 대상을 user_memory_storage로 변경

#         print(f"--- '/api/complaints' 처리 완료, {len(data)}개 항목 반환 ---")
#         return jsonify(data)

#     except Exception as e:
#         print(f"🚨 고소장 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그에 요청자 이메일 포함
#         traceback.print_exc()
#         return jsonify({"error":"고소장 목록 생성 실패", "detail": str(e)}), 500

# @api_bp.route("/supplementaries")
# def list_supplementaries():
#     """보충이유서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
#     id_token = None
#     uploader_uid = None
#     requester_email = '이메일 정보 없음'

#     # user_memory_storage 전역 변수 사용 명시 ▼▼▼
#     global user_memory_storage

#     if not auth:
#         print("🚨 /api/supplementaries: Firebase Auth object not available.")
#         return jsonify({"error": "Server authentication system error"}), 500

#     try:
#         auth_header = request.headers.get('Authorization')
#         if not auth_header or not auth_header.startswith('Bearer '):
#             print("🚨 /api/supplementaries: 인증 토큰 없음.")
#             return jsonify({"error": "인증 토큰이 필요합니다."}), 401

#         id_token = auth_header.split('Bearer ')[1]
#         try:
#             decoded_token = auth.verify_id_token(id_token)
#             uploader_uid = decoded_token.get('uid')
#             requester_email = decoded_token.get('email', '이메일 정보 없음')

#             if requester_email == '이메일 정보 없음':
#                  print("🚨 /api/supplementaries: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
#                  return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401

#             print(f"ℹ️ /api/supplementaries 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")

#         except Exception as auth_err:
#             print(f"🚨 /api/supplementaries: 토큰 검증 오류: {auth_err}")
#             traceback.print_exc()
#             is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
#             error_status_code = 401 if is_invalid_token_error else 500
#             return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500

#         print(f"--- '/api/supplementaries' 데이터 조회 시작 (요청자: {requester_email}) ---")
#         # user_memory_storage 전체에서 보충이유서 목록을 가져오되, 요청자의 이메일과 토픽("보충이유서")으로 필터링 ▼▼▼
#         data = _create_summary_list(user_memory_storage, requester_email, required_topic="보충이유서") # <--- 조회 대상을 user_memory_storage로 변경

#         print(f"--- '/api/supplementaries' 처리 완료, {len(data)}개 항목 반환 ---")
#         return jsonify(data)

#     except Exception as e:
#         print(f"🚨 보충이유서 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그에 요청자 이메일 포함
#         traceback.print_exc()
#         return jsonify({"error":"보충이유서 목록 생성 실패", "detail": str(e)}), 500


# @api_bp.route("/prosecutor")
# def list_prosecutor_opinions():
#     """검찰의견서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
#     id_token = None
#     uploader_uid = None
#     requester_email = '이메일 정보 없음'

#     # user_memory_storage 전역 변수 사용 명시 ▼▼▼
#     global user_memory_storage

#     if not auth:
#         print("🚨 /api/prosecutor: Firebase Auth object not available.")
#         return jsonify({"error": "Server authentication system error"}), 500

#     try:
#         auth_header = request.headers.get('Authorization')
#         if not auth_header or not auth_header.startswith('Bearer '):
#             print("🚨 /api/prosecutor: 인증 토큰 없음.")
#             return jsonify({"error": "인증 토큰이 필요합니다."}), 401

#         id_token = auth_header.split('Bearer ')[1]
#         try:
#             decoded_token = auth.verify_id_token(id_token)
#             uploader_uid = decoded_token.get('uid')
#             requester_email = decoded_token.get('email', '이메일 정보 없음')

#             if requester_email == '이메일 정보 없음':
#                  print("🚨 /api/prosecutor: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.")
#                  return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401

#             print(f"ℹ️ /api/prosecutor 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")

#         except Exception as auth_err:
#             print(f"🚨 /api/prosecutor: 토큰 검증 오류: {auth_err}")
#             traceback.print_exc()
#             is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
#             error_status_code = 401 if is_invalid_token_error else 500
#             return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500

#         print(f"--- '/api/prosecutor' 데이터 조회 시작 (요청자: {requester_email}) ---")
#         # user_memory_storage 전체에서 검찰의견서 목록을 가져오되, 요청자의 이메일과 토픽("검찰의견서")으로 필터링 ▼▼▼
#         data = _create_summary_list(user_memory_storage, requester_email, required_topic="검찰의견서") # <--- 조회 대상을 user_memory_storage로 변경

#         print(f"--- '/api/prosecutor' 처리 완료, {len(data)}개 항목 반환 ---")
#         return jsonify(data)

#     except Exception as e:
#         print(f"🚨 검찰의견서 목록 생성 오류 (요청자: {requester_email}): {e}")
#         traceback.print_exc()
#         return jsonify({"error":"검찰의견서 목록 생성 실패", "detail": str(e)}), 500

# @api_bp.route("/agreements")
# def list_agreements(): # 함수 이름을 list_agreements 로 변경
#     """합의서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
#     id_token = None
#     uploader_uid = None # 요청자 UID (로깅용)
#     requester_email = '이메일 정보 없음' # 요청자 이메일

#     # user_memory_storage 전역 변수 사용 명시 ▼▼▼
#     global user_memory_storage

#     # auth 객체가 초기화되어 있는지 확인합니다. (실제 auth 또는 Mock)
#     if not auth:
#         print("🚨 /api/agreements: Firebase Auth object not available.") # 로그 메시지 수정
#         return jsonify({"error": "Server authentication system error"}), 500

#     try:
#         # --- ▼▼▼ ID 토큰 확인 및 요청자 UID, 이메일 얻기 (필수!) ▼▼▼ ---
#         auth_header = request.headers.get('Authorization')
#         if not auth_header or not auth_header.startswith('Bearer '):
#             print("🚨 /api/agreements: 인증 토큰 없음.") # 로그 메시지 수정
#             # 목록 조회를 위해 인증 필수
#             return jsonify({"error": "인증 토큰이 필요합니다."}), 401

#         id_token = auth_header.split('Bearer ')[1]
#         try:
#             decoded_token = auth.verify_id_token(id_token) # 토큰 검증
#             uploader_uid = decoded_token.get('uid') # 요청자 UID (get 사용)
#             requester_email = decoded_token.get('email', '이메일 정보 없음') # 요청자 이메일 추출

#             if requester_email == '이메일 정보 없음':
#                 print("🚨 /api/agreements: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.") # 로그 메시지 수정
#                 # 필터링을 위해 이메일 필수
#                 return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401 # 또는 403

#             print(f"ℹ️ /api/agreements 요청 사용자 UID: {uploader_uid}, Email: {requester_email}") # 로그 메시지 수정
#             # 관리자 체크는 _create_summary_list 내부에서 이메일로 수행됩니다.

#         except Exception as auth_err: # 토큰 검증/정보 추출 오류
#             print(f"🚨 /api/agreements: 토큰 검증 오류: {auth_err}") # 로그 메시지 수정
#             traceback.print_exc()
#             is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
#             error_status_code = 401 if is_invalid_token_error else 500
#             return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500
#         # --- ▲▲▲ ID 토큰 확인 및 요청자 UID, 이메일 얻기 ▲▲▲ ---

#         # --- 인증 통과 후 로직 수행 (데이터 필터링) ---
#         print(f"--- '/api/agreements' 데이터 조회 시작 (요청자: {requester_email}) ---") # 로그 메시지 수정
#         # user_memory_storage 전체에서 합의서 목록을 가져오되, 요청자의 이메일과 토픽("합의서")으로 필터링 ▼▼▼
#         # _create_summary_list 함수는 다른 곳에 정의되어 있으며, user_memory_storage 구조를 탐색하고 필터링합니다.
#         data = _create_summary_list(user_memory_storage, requester_email, required_topic="합의서") # <--- 조회 대상을 user_memory_storage로 변경하고 토픽을 "합의서"로 변경

#         print(f"--- '/api/agreements' 처리 완료, {len(data)}개 항목 반환 ---") # 로그 메시지 수정
#         return jsonify(data)

#     except Exception as e:
#         print(f"🚨 합의서 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그 메시지 및 에러 메시지 수정
#         traceback.print_exc()
#         return jsonify({"error":"합의서 목록 생성 실패", "detail": str(e)}), 500 # 에러 메시지 수정

@api_bp.route("/clients", methods=['GET'])
def list_my_clients():
    """
    인증된 사용자의 클라이언트 목록을 반환합니다.
    각 클라이언트별 첫 상담일, 마지막 활동일, 문서 목록 정보를 포함합니다.
    """
    requester_uid = None
    requester_email = '이메일 정보 없음'

    global user_memory_storage, auth
    if not auth:
        print("🚨 /api/clients: Firebase Auth object not available.")
        return jsonify({"error": "Server authentication system error"}), 500

    print(f"--- '/api/clients' 클라이언트 목록 조회 요청 처리 시작 ---")

    try:
        # --- 인증 로직 (기존과 동일) ---
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401
        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            requester_uid = decoded_token.get('uid')
            requester_email = decoded_token.get('email', '이메일 정보 없음')
            if not requester_uid:
                return jsonify({"error": "인증 토큰에 사용자 정보가 없습니다."}), 401
            print(f"ℹ️ /api/clients 요청 사용자 UID: {requester_uid}, Email: {requester_email}")
        except Exception as auth_err:
            print(f"🚨 /api/clients: 토큰 검증 오류: {auth_err}")
            # traceback.print_exc() # 상세 오류 필요시 주석 해제
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 401
        # --- 인증 완료 ---

        # --- 클라이언트별 데이터 집계 시작 ---
        user_data = user_memory_storage.get(requester_uid, {})
        if not user_data:
            print(f"ℹ️ /api/clients: 사용자 '{requester_uid}' 데이터 없음. 빈 목록 반환.")
            return jsonify([])

        # 클라이언트 식별자(key)를 기준으로 데이터를 집계할 딕셔너리
        clients_aggregated_data = {}

        # 타임스탬프 파싱 및 비교를 위한 헬퍼 함수
        def parse_timestamp(ts_str):
            if not ts_str or not isinstance(ts_str, str):
                return None
            try:
                # ISO 8601 형식 처리 (시간대 정보 포함/미포함 모두 고려)
                # 'Z'를 +00:00으로 변경하여 UTC로 명시적 처리
                dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                # 시간대 정보가 없다면 UTC로 가정 (일관성을 위해)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                print(f"WARN: Invalid timestamp format encountered: {ts_str}")
                return None

        # 사용자의 모든 데이터 항목 순회
        for storage_key, data_item in user_data.items():
            if not isinstance(data_item, dict): continue # 유효하지 않은 항목 스킵

            metadata = data_item.get('metadata', {})
            client_name = metadata.get('name', '')
            client_phone = metadata.get('phone', '')
            # 이메일은 client_email_target 또는 email 또는 user_email 에서 가져오도록 수정
            client_email = metadata.get('client_email_target', metadata.get('email', metadata.get('user_email', '')))

            # 클라이언트 식별자 생성 (이름 또는 전화번호 필수)
            if not client_name and not client_phone: continue
            client_identifier = f"{client_name}|{client_phone}|{client_email}" # 고유 식별자

            # 현재 항목의 타임스탬프 파싱
            current_timestamp_str = data_item.get('timestamp')
            current_dt = parse_timestamp(current_timestamp_str)

            # 집계 딕셔너리에 클라이언트 정보 추가 또는 업데이트
            if client_identifier not in clients_aggregated_data:
                # 새 클라이언트 발견 시 초기화
                clients_aggregated_data[client_identifier] = {
                    'identifier': client_identifier,
                    'name': client_name if client_name else '이름 정보 없음',
                    'phone': client_phone if client_phone else '전화번호 정보 없음',
                    'region': metadata.get('region', '지역 정보 없음'),
                    'email': client_email if client_email else '이메일 정보 없음',
                    'earliest_timestamp': current_dt, # 첫 발견 시점의 타임스탬프로 초기화
                    'latest_timestamp': current_dt,   # 첫 발견 시점의 타임스탬프로 초기화
                    'documents': [] # 문서 목록 초기화
                }
            else:
                # 기존 클라이언트 - 타임스탬프 업데이트
                agg_data = clients_aggregated_data[client_identifier]
                if current_dt:
                    if agg_data['earliest_timestamp'] is None or current_dt < agg_data['earliest_timestamp']:
                        agg_data['earliest_timestamp'] = current_dt
                    if agg_data['latest_timestamp'] is None or current_dt > agg_data['latest_timestamp']:
                        agg_data['latest_timestamp'] = current_dt

            # 문서 정보 수집 (key_topic이 있는 항목을 문서로 간주)
            key_topic = metadata.get('key_topic')
            if key_topic: # 토픽이 있어야 문서로 간주
                 clients_aggregated_data[client_identifier]['documents'].append({
                     'topic': key_topic,
                     'name': metadata.get('document_name', key_topic), # 문서 제목 (없으면 토픽 사용)
                     'date': current_timestamp_str.split('T')[0] if current_timestamp_str else None, # 날짜 부분 (YYYY-MM-DD)
                     'timestamp': current_timestamp_str, # 전체 타임스탬프 (정렬 및 상세 정보용)
                     'storage_key': storage_key # 상세 보기용 키
                 })

        # --- 최종 결과 리스트 생성 ---
        clients_list = []
        # 파이썬에서 사용 가능한 가장 오래된 시간 (시간대 정보 포함)
        min_datetime_aware = datetime.min.replace(tzinfo=timezone.utc)

        for client_data in clients_aggregated_data.values():
            # 타임스탬프를 ISO 문자열로 변환 (JSON 호환)
            earliest_ts_str = client_data['earliest_timestamp'].isoformat() if client_data['earliest_timestamp'] else None
            latest_ts_str = client_data['latest_timestamp'].isoformat() if client_data['latest_timestamp'] else None

            # documents 리스트도 최신순으로 정렬 (선택 사항)
            try:
                client_data['documents'].sort(
                    key=lambda doc: parse_timestamp(doc.get('timestamp')) or min_datetime_aware,
                    reverse=True
                )
            except Exception as doc_sort_err:
                 print(f"WARN: Failed to sort documents for client {client_data['identifier']}: {doc_sort_err}")


            clients_list.append({
                'identifier': client_data['identifier'],
                'name': client_data['name'],
                'phone': client_data['phone'],
                'region': client_data['region'],
                'email': client_data['email'],
                'earliest_timestamp': earliest_ts_str, # 첫 상담일
                'latest_timestamp': latest_ts_str,   # 마지막 활동일 (정렬 및 표시에 사용 가능)
                'documents': client_data['documents'] # 문서 목록 배열
                # 'status': '수임' # 상태는 여기서 고정해도 되고, 프론트에서 해도 됨
            })

        # 최종 클라이언트 목록을 마지막 활동일 기준 내림차순 정렬
        try:
             clients_list.sort(
                 key=lambda x: parse_timestamp(x.get('latest_timestamp')) or min_datetime_aware,
                 reverse=True
             )
             print(f"--- '/api/clients' 최종 목록 정렬 완료 ---")
        except Exception as final_sort_err:
             print(f"WARN: Failed to sort final client list: {final_sort_err}")


        print(f"--- '/api/clients' 처리 완료, 총 {len(clients_list)}개 클라이언트 반환 ---")
        return jsonify(clients_list)

    except Exception as e:
        print(f"🚨 사용자 클라이언트 목록 생성 오류 (요청자 UID: {requester_uid}): {e}")
        traceback.print_exc()
        return jsonify({"error":"클라이언트 목록 생성 실패", "detail": str(e)}), 500

@api_bp.route("/summaries")
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

@api_bp.route("/memory/<string:storage_key>", methods=['GET'])
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

@api_bp.route("/debug/memory")
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



# 나머지 기존 Flask 라우트 및 코드들 ...
# if __name__ == '__main__':
#     app.run(...)
@api_bp.route("/admin/files/list", methods=['GET'])
def admin_list_files_logic():
    print(f"--- '/admin/files/list' [Workaround] 요청 처리 시작 ---")
    # 1. 인증 (기존과 동일)
    auth_header = request.headers.get('Authorization')
    id_token = None
    uploader_uid = None
    if auth_header and auth_header.startswith('Bearer '): id_token = auth_header.split('Bearer ')[1]
    if not id_token: return jsonify({"error": "인증 토큰 필요"}), 401
    try:
        decoded_token = auth.verify_id_token(id_token)
        uploader_uid = decoded_token['uid']
        print(f"ℹ️ /admin/files/list [Workaround] 요청자 UID: {uploader_uid}")
    except Exception as e:
        print(f"🚨 /admin/files/list [Workaround] 토큰 검증 오류: {e}")
        return jsonify({"error": "토큰 검증 오류", "detail": str(e)}), 401

    # 2. 검색 조건 (기존과 동일)
    search_name = request.args.get('name', '').strip()
    search_phone = request.args.get('phone', '').strip()
    search_region = request.args.get('region', '').strip()
    search_email = request.args.get('clientEmail', '').strip()
    search_key_topic = request.args.get('key', '').strip()
    print(f"ℹ️ 검색 조건 - 이름: '{search_name}', 전화: '{search_phone}', 지역: '{search_region}', 이메일: '{search_email}', 토픽: '{search_key_topic}'")
    if not any([search_name, search_phone, search_region, search_email, search_key_topic]):
         print("⚠️ 검색 조건 없음. 빈 목록 반환.")
         return jsonify({"files": [], "message": "검색 조건 입력 필요"}), 200

    # 3. 데이터 검색 및 필터링 (Workaround 수정)
    admin_storage = user_memory_storage.get(uploader_uid, {})
    found_files_metadata = []
    print(f"ℹ️ '{uploader_uid}' 관리자 저장 공간 {len(admin_storage)}개 항목 검색 시작 [Workaround].")

    for storage_key, data in admin_storage.items():
        metadata = data.get('metadata', {})
        # 검색 조건 매칭
        match = True
        if search_name and metadata.get('name') != search_name: match = False
        if search_phone and metadata.get('phone') != search_phone: match = False
        if search_region and metadata.get('region') != search_region: match = False
        if search_email and metadata.get('email') != search_email: match = False
        if search_key_topic and metadata.get('key_topic') != search_key_topic: match = False

        if not match: continue # 조건 안 맞으면 다음 항목으로

        print(f"  ✓ Entry Matched: storage_key='{storage_key}'")
        files_info_list = metadata.get('uploaded_files_info', [])
        print(f"    - Found {len(files_info_list)} file info entries.")

        for file_info in files_info_list:
            original_filename = file_info.get('original_filename')
            processed_filename_stored = file_info.get('processed_filename') # 저장된 값 (없을 수 있음)
            temp_path_stored = file_info.get('temp_path') # ★★★ 이게 저장되어 있어야 함 ★★★
            file_type = file_info.get('type')

            # Workaround 핵심: original_filename 과 temp_path 가 있어야 진행 가능
            if not original_filename:
                 print(f"    ⚠️ SKIPPING file in '{storage_key}' due to MISSING 'original_filename'.")
                 continue
            if not temp_path_stored:
                 print(f"    ⚠️ SKIPPING file '{original_filename}' (in '{storage_key}') due to MISSING 'temp_path'. Download impossible.")
                 continue # temp_path 없으면 다운로드 불가하므로 스킵

            # 다운로드 식별자 결정: processed_filename 있으면 그걸 쓰고, 없으면 original_filename 사용
            download_identifier = processed_filename_stored if processed_filename_stored else original_filename
            is_fallback = not bool(processed_filename_stored)

            # 필요한 정보가 모두 있으므로 결과 목록에 추가
            file_entry = {
                'storage_key': storage_key,
                'original_filename': original_filename,
                # JS 호환성을 위해 'processed_filename' 필드에 식별자 전달
                'processed_filename': download_identifier,
                'type': file_type,
                'size': file_info.get('size'),
                'upload_timestamp': data.get('timestamp'),
                'key_topic': metadata.get('key_topic'),
                'target_name': metadata.get('name'),
                'target_phone': metadata.get('phone'),
                'target_region': metadata.get('region'),
                'target_email': metadata.get('email'),
                # 'is_fallback_identifier': is_fallback # 디버깅용 플래그 (옵션)
            }
            status = f"Identifier: {download_identifier}" + (" (Original used)" if is_fallback else "")
            print(f"    + ADDING file: '{original_filename}' (Type: {file_type}, {status}, SK: {storage_key})")
            found_files_metadata.append(file_entry)

    print(f"✅ 검색 완료 [Workaround]. 총 {len(found_files_metadata)}개의 파일 메타데이터를 반환합니다.")
    return jsonify({"files": found_files_metadata}), 200


@api_bp.route("/api/memory/download_text/<string:storage_key>", methods=['GET'])
def download_memory_text(storage_key):
    """
    주어진 storage_key에 해당하는 메모리 데이터의 텍스트 내용(기본: 요약)을
    .txt 파일로 다운로드합니다. 인증 및 소유권 확인이 필요합니다.
    """
    print(f"--- '/api/memory/download_text/{storage_key}' 요청 처리 시작 ---")
    uploader_uid = None

    # --- 인증 로직 (기존 /api/memory/<storage_key> 와 동일) ---
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        return jsonify({"error": "인증 토큰 필요"}), 401
    id_token = auth_header.split('Bearer ')[1]
    try:
        # 실제 Firebase Admin SDK의 auth 객체를 사용해야 합니다.
        # auth 객체가 routes.py에서 사용 가능하도록 초기화/import 필요
        global auth # auth 객체가 전역적으로 사용 가능하다고 가정
        decoded_token = auth.verify_id_token(id_token)
        uploader_uid = decoded_token['uid']
        print(f"ℹ️ /api/memory/download_text 요청 사용자 UID: {uploader_uid}")
    except Exception as e:
        print(f"🚨 /api/memory/download_text: 토큰 검증 오류: {e}")
        # traceback.print_exc() # 필요시 상세 오류 출력
        return jsonify({"error": "인증 오류", "detail": str(e)}), 401
    # --- 인증 로직 끝 ---

    data_item = None
    # --- 데이터 조회 로직 (사용자 데이터 우선 확인) ---
    # user_memory_storage 가 routes.py 에서 사용 가능해야 함
    global user_memory_storage
    if uploader_uid and uploader_uid in user_memory_storage and storage_key in user_memory_storage[uploader_uid]:
        data_item = user_memory_storage[uploader_uid][storage_key]
    # (필요시 admin_memory_storage 확인 로직 추가)

    if not data_item:
        print(f"⚠️ Key '{storage_key}' 를 사용자 '{uploader_uid}' 메모리에서 찾을 수 없음.")
        return jsonify({"error": "데이터 찾을 수 없음"}), 404
    # --- 데이터 조회 끝 ---

    # --- 다운로드할 텍스트 내용 선택 ---
    content_type_requested = request.args.get('content', 'summary') # 기본값 'summary'
    text_to_download = None
    filename_part = "document" # 기본 파일명 부분

    if content_type_requested == 'summary' and 'summary' in data_item:
        text_to_download = data_item['summary']
        filename_part = "summary"
    elif content_type_requested == 'content' and 'files_content' in data_item: # 예: OCR 결과
        text_to_download = data_item['files_content']
        filename_part = "content"
    elif content_type_requested == 'original' and 'original' in data_item: # 예: STT 결과
        text_to_download = data_item['original']
        filename_part = "original"
    else: # 요청한 타입이 없거나 기본 'summary'가 없을 경우
         if 'summary' in data_item: # fallback으로 summary 시도
             text_to_download = data_item['summary']
             filename_part = "summary"
         elif 'files_content' in data_item: # 그 다음 files_content 시도
              text_to_download = data_item['files_content']
              filename_part = "content"
         elif 'original' in data_item: # 마지막으로 original 시도
              text_to_download = data_item['original']
              filename_part = "original"


    # --- ▼▼▼ 디버깅 로그 추가 ▼▼▼ ---
    summary_value_debug = data_item.get('summary') # .get() 사용하면 키가 없어도 오류 안 남
    files_content_value_debug = data_item.get('files_content')
    original_value_debug = data_item.get('original')
    print(f"DEBUG LOG [download_memory_text]: storage_key='{storage_key}', requested='{content_type_requested}'")
    print(f"DEBUG LOG [download_memory_text]: Found data_item? {'Yes' if data_item else 'No'}")
    print(f"DEBUG LOG [download_memory_text]: Value of data_item['summary'] is: '{summary_value_debug}'")
    print(f"DEBUG LOG [download_memory_text]: Type of data_item['summary'] is: {type(summary_value_debug)}")
    print(f"DEBUG LOG [download_memory_text]: Value of data_item['files_content'] is present? {'Yes' if files_content_value_debug else 'No'}")
    print(f"DEBUG LOG [download_memory_text]: Value of data_item['original'] is present? {'Yes' if original_value_debug else 'No'}")
    print(f"DEBUG LOG [download_memory_text]: Value selected for text_to_download: '{str(text_to_download)[:100]}...'") # 값의 일부만 출력
    print(f"DEBUG LOG [download_memory_text]: Type of selected text_to_download: {type(text_to_download)}")
    # --- ▲▲▲ 디버깅 로그 추가 끝 ▲▲▲ ---


    # 404 반환 조건 검사
    if not text_to_download or not isinstance(text_to_download, str):
         print(f"⚠️ Key '{storage_key}' 에 다운로드할 텍스트 내용(요청: {content_type_requested}, 선택됨: {filename_part}) 없음. Returning 404.") # 로그 명확화
         return jsonify({"error": "다운로드할 텍스트 내용 없음"}), 404
    # --- 텍스트 내용 선택 끝 ---


    # --- 다운로드 파일명 생성 ---
    # sanitize_filename 함수가 routes.py에서 사용 가능해야 함
    global sanitize_filename
    metadata = data_item.get('metadata', {})
    client_name = sanitize_filename(metadata.get('name', 'unknown'))
    key_topic = sanitize_filename(metadata.get('key_topic', 'doc'))
    # 타임스탬프에서 날짜 부분만 추출 (YYYY-MM-DD 형식)
    timestamp_str = data_item.get('timestamp', datetime.now().isoformat()).split('T')[0]
    download_filename = f"{client_name}_{key_topic}_{timestamp_str}_{filename_part}.txt"
    # --- 파일명 생성 끝 ---

    # --- 텍스트 파일 생성 및 전송 ---
    try:
        # 텍스트를 UTF-8 바이트로 인코딩
        text_bytes = text_to_download.encode('utf-8')
        # BytesIO를 사용하여 메모리 내 바이트 스트림 생성
        buffer = BytesIO(text_bytes)
        buffer.seek(0) # 스트림 포인터를 처음으로 이동

        print(f"✅ 텍스트 파일 전송 시작: {download_filename} ({len(text_bytes)} bytes)")
        # send_file을 사용하여 메모리 버퍼에 있는 내용을 파일로 전송
        return send_file(
            buffer,
            mimetype='text/plain',           # Mime 타입 지정
            as_attachment=True,              # 첨부파일로 다운로드되도록 설정
            download_name=download_filename  # 다운로드될 파일 이름 지정
        )
    except Exception as e:
        print(f"🚨🚨🚨 텍스트 파일 생성/전송 중 오류 발생: {e}")
        traceback.print_exc()
        return jsonify({"error": "텍스트 파일 다운로드 중 서버 오류", "detail": str(e)}), 500
    # --- 텍스트 파일 생성 및 전송 끝 ---
    # --- 텍스트 파일 생성 및 전송 끝 ---


# --- /admin/files/download (Workaround 수정) ---
@api_bp.route("/admin/files/download", methods=['GET'])
def admin_download_file_logic():
    print(f"--- '/admin/files/download' [Workaround] 요청 처리 시작 ---")

    # 1. 인증 및 uploader_uid 획득 (수정 완료된 버전)
    auth_header = request.headers.get('Authorization')
    id_token = None
    uploader_uid = None # 초기화

    if auth_header and auth_header.startswith('Bearer '):
        id_token = auth_header.split('Bearer ')[1]

    if not id_token:
        print("🚨 /admin/files/download: Authorization 헤더 없거나 Bearer 토큰 아님.")
        return jsonify({"error": "인증 토큰 필요"}), 401

    try:
        # 토큰 검증 시도
        decoded_token = auth.verify_id_token(id_token)
        uploader_uid = decoded_token['uid']
        print(f"ℹ️ /admin/files/download [Workaround] 요청자 UID: {uploader_uid}")
    except Exception as e:
        # 오류 발생 시 로그 출력! (상세 내용 포함)
        print(f"🚨 /admin/files/download [Workaround] 토큰 검증 오류: {e}")
        return jsonify({"error": "인증 오류", "detail": str(e)}), 401

    # 2. 파라미터 가져오기
    storage_key_to_download = request.args.get('storageKey', '').strip()
    # list API가 반환한 식별자 (processed_filename 또는 original_filename)
    identifier_from_request = request.args.get('processedFilename', '').strip()

    print(f"ℹ️ 다운로드 요청 [Workaround] - SK: '{storage_key_to_download}', Identifier(PFN/Orig): '{identifier_from_request}'")
    if not storage_key_to_download or not identifier_from_request:
        print("🚨 필수 파라미터 누락 (storageKey 또는 processedFilename)")
        return jsonify({"error": "필수 파라미터 누락"}), 400

    # 3. 스토리지에서 파일 정보 찾기
    # user_memory_storage 구조 및 uploader_uid 유효성 검사
    if uploader_uid not in user_memory_storage or storage_key_to_download not in user_memory_storage.get(uploader_uid, {}):
         print(f"🚨 데이터 항목 없음 - UID: {uploader_uid}, SK: {storage_key_to_download}")
         return jsonify({"error": "데이터 항목 없음", "storageKey": storage_key_to_download}), 404

    data_entry = user_memory_storage[uploader_uid][storage_key_to_download]
    files_info_list = data_entry.get('metadata', {}).get('uploaded_files_info', [])

    file_info_to_download = None
    for file_info in files_info_list:
        # 식별자와 일치하는 파일 정보 찾기 (processed_filename 우선, 없으면 original_filename)
        if file_info.get('processed_filename') and file_info.get('processed_filename') == identifier_from_request:
            file_info_to_download = file_info; print(f"  -> Found file by matching stored 'processed_filename'.")
            break
        elif not file_info.get('processed_filename') and file_info.get('original_filename') == identifier_from_request:
             file_info_to_download = file_info; print(f"  -> Found file by matching stored 'original_filename' (processed_filename was missing).")
             break

    if not file_info_to_download:
        print(f"🚨 SK '{storage_key_to_download}' 에서 Identifier '{identifier_from_request}' 와 일치하는 파일 정보 못 찾음.")
        return jsonify({"error": "파일 정보 찾기 실패", "identifier": identifier_from_request}), 404

    # 4. temp_path 로 실제 파일 찾고 전송
    temp_file_path = file_info_to_download.get('temp_path') # ★★★ 중요: 업로드 시 저장 필수 ★★★
    original_filename_for_download = file_info_to_download.get('original_filename', 'downloaded_file')

    if not temp_file_path:
        print(f"🚨 CRITICAL: Identifier '{identifier_from_request}' 파일 정보는 찾았으나 'temp_path'가 저장 안됨! 업로드 로직 확인 필요.")
        return jsonify({"error": "서버 파일 경로(temp_path) 정보 누락"}), 500

    if not os.path.exists(temp_file_path):
        print(f"🚨 CRITICAL: 서버에 파일 없음! Path: {temp_file_path}")
        return jsonify({"error": "서버 파일 찾기 실패"}), 500

    # --- 파일 전송 시도 ---
    print(f"✅ 파일 전송 시작 [Workaround]: {temp_file_path} (다운로드 이름: {original_filename_for_download})")
    try:
        # 실제 파일 전송
        response = send_file(
            temp_file_path,
            as_attachment=True,
            download_name=original_filename_for_download,
            # mimetype=file_info_to_download.get('mime_type') # 필요시 마임타입 지정
        )
        return response # 성공 시 Response 객체 반환
    except Exception as e:
        # send_file 자체에서 오류 발생 시 상세 내용 로깅
        print(f"🚨🚨🚨 파일 전송 중 오류 발생 [Workaround]: {e}")
        traceback.print_exc() # <<< 상세 Traceback 출력!
        return jsonify({"error": "파일 전송 중 서버 오류", "detail": str(e)}), 500

    # 이 함수는 모든 경로에서 return 문을 가지므로, 아래 코드는 이론상 도달하지 않아야 합니다.
    # print("🚨🚨🚨 CRITICAL: Reached end of download function unexpectedly!")
    # return jsonify({"error": "알 수 없는 서버 오류 (코드 흐름 이상)"}), 500


@api_bp.route("/calendar/memos", methods=['GET'])
def get_calendar_memos():
    """
    인증된 사용자의 캘린더 메모 목록을 FullCalendar 이벤트 형식으로 반환합니다.
    """
    print(f"--- '/api/calendar/memos' [GET] 요청 처리 시작 ---")
    requester_uid = None
    requester_email = '이메일 정보 없음'
    global user_memory_storage, auth

    if not auth:
        print("🚨 /api/calendar/memos: Firebase Auth object not available.")
        return jsonify({"error": "서버 인증 시스템 오류"}), 500

    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증 필수) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/calendar/memos: 인증 토큰 없음.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token)
            requester_uid = decoded_token.get('uid')
            requester_email = decoded_token.get('email', '이메일 정보 없음')
            if not requester_uid:
                 print("🚨 /api/calendar/memos: 유효 토큰이나 UID 정보 없음.")
                 return jsonify({"error": "인증 토큰에 사용자 정보가 없습니다."}), 401
            print(f"ℹ️ /api/calendar/memos [GET] 요청 사용자 UID: {requester_uid}, Email: {requester_email}")
        except Exception as auth_err:
            print(f"🚨 /api/calendar/memos: 토큰 검증 오류: {auth_err}")
            # traceback.print_exc() # 필요시 상세 오류 출력
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 401
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 완료 ▲▲▲ ---

        # --- 사용자 데이터 조회 및 메모 필터링 ---
        calendar_memos = []
        user_specific_data = user_memory_storage.get(requester_uid, {})

        print(f"ℹ️ UID '{requester_uid}'의 데이터 {len(user_specific_data)}개 확인. 'memo' 타입 필터링 시작.")

        for storage_key, data_item in user_specific_data.items():
            if isinstance(data_item, dict) and data_item.get('type') == 'memo':
                try:
                    memo_date = data_item.get('date') # YYYY-MM-DD 형식이어야 함
                    memo_text = data_item.get('text', '')
                    memo_timestamp = data_item.get('timestamp') # 생성/수정 시각

                    if memo_date: # 날짜가 있어야 캘린더에 표시 가능
                        calendar_memos.append({
                            'id': storage_key,           # 메모 고유 ID (storage_key 사용)
                            'title': memo_text,          # 이벤트 제목 = 메모 내용
                            'start': memo_date,          # 이벤트 시작일 (YYYY-MM-DD)
                            'allDay': True,              # 하루 종일 이벤트로 처리
                            'extendedProps': {           # 클릭 시 상세 정보 표시용
                                'text': memo_text,
                                'timestamp': memo_timestamp,
                                'type': 'memo'           # 타입 명시
                            },
                            # 필요시 색상 등 추가 가능
                            # 'color': '#ff9f89' # 예시: 메모 이벤트 색상
                        })
                    else:
                         print(f"⚠️ 메모 스킵 (키: {storage_key}): 'date' 필드 누락")

                except Exception as item_e:
                    print(f"🚨 메모 항목 (키: {storage_key}) 처리 중 오류 발생: {item_e}")
                    traceback.print_exc()

        print(f"--- '/api/calendar/memos' [GET] 처리 완료. 총 {len(calendar_memos)}개 메모 반환 ---")
        return jsonify(calendar_memos), 200

    except Exception as e:
        print(f"🚨 '/api/calendar/memos' [GET] 요청 처리 중 예외 발생: {e}")
        traceback.print_exc()
        return jsonify({"error": "캘린더 메모 조회 중 서버 오류 발생", "detail": str(e)}), 500


@api_bp.route("/calendar/memos", methods=['POST'])
def add_calendar_memo():
    """
    인증된 사용자의 특정 날짜에 새 캘린더 메모를 추가합니다.
    """
    print(f"--- '/api/calendar/memos' [POST] 요청 처리 시작 ---")
    requester_uid = None
    requester_email = '이메일 정보 없음'
    global user_memory_storage, auth

    if not auth:
        print("🚨 /api/calendar/memos [POST]: Firebase Auth object not available.")
        return jsonify({"error": "서버 인증 시스템 오류"}), 500

    # --- ▼▼▼ 인증 및 UID 얻기 (필수) ▼▼▼ ---
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        print("🚨 /api/calendar/memos [POST]: 인증 토큰 없음.")
        return jsonify({"error": "인증 토큰이 필요합니다."}), 401

    id_token = auth_header.split('Bearer ')[1]
    try:
        decoded_token = auth.verify_id_token(id_token)
        requester_uid = decoded_token.get('uid')
        requester_email = decoded_token.get('email', '이메일 정보 없음')
        if not requester_uid:
             print("🚨 /api/calendar/memos [POST]: 유효 토큰이나 UID 정보 없음.")
             return jsonify({"error": "인증 토큰에 사용자 정보가 없습니다."}), 401
        print(f"ℹ️ /api/calendar/memos [POST] 요청 사용자 UID: {requester_uid}, Email: {requester_email}")
    except Exception as auth_err:
        print(f"🚨 /api/calendar/memos [POST]: 토큰 검증 오류: {auth_err}")
        return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 401
    # --- ▲▲▲ 인증 및 UID 얻기 완료 ▲▲▲ ---

    # --- 입력 데이터 확인 ---
    if not request.is_json:
        print("🚨 /api/calendar/memos [POST]: 요청 형식이 JSON이 아님.")
        return jsonify({"error": "요청 본문은 JSON 형식이어야 합니다."}), 400

    data = request.get_json()
    memo_date_str = data.get('date')
    memo_text = data.get('text')

    if not memo_date_str or not memo_text:
        print("🚨 /api/calendar/memos [POST]: 필수 필드 누락 ('date', 'text').")
        return jsonify({"error": "필수 필드('date', 'text')가 누락되었습니다."}), 400

    # 날짜 형식 검증 (YYYY-MM-DD)
    try:
        datetime.strptime(memo_date_str, '%Y-%m-%d')
    except ValueError:
        print(f"🚨 /api/calendar/memos [POST]: 잘못된 날짜 형식: {memo_date_str}")
        return jsonify({"error": "날짜는 'YYYY-MM-DD' 형식이어야 합니다."}), 400

    memo_id = None # 롤백을 위해 초기화

    try:
        # --- 메모 데이터 생성 및 저장 ---
        # 고유 ID 생성 (타임스탬프 기반)
        memo_id = f"memo_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"

        memo_data = {
            'type': 'memo',
            'date': memo_date_str,
            'text': memo_text,
            'timestamp': datetime.now(timezone.utc).isoformat(), # UTC 시간으로 저장
            'metadata': { # 다른 데이터와의 일관성을 위해 metadata 사용
                'user_email': requester_email # 작성자 이메일 저장 (선택적)
            }
        }

        # 사용자 저장 공간 확인 및 생성
        if requester_uid not in user_memory_storage:
            user_memory_storage[requester_uid] = {}
            print(f"DEBUG: Created new user folder in memory for UID: {requester_uid} (from /calendar/memos [POST])")

        # 메모 저장
        user_memory_storage[requester_uid][memo_id] = memo_data
        print(f"✅ 새 메모 저장됨 (UID: {requester_uid}, Memo ID: {memo_id}, Date: {memo_date_str})")

        # 성공 응답 (생성된 메모 정보 포함)
        # FullCalendar 이벤트 형식으로 맞춰서 반환하면 프론트에서 바로 추가하기 용이
        response_event = {
             'id': memo_id,
             'title': memo_text,
             'start': memo_date_str,
             'allDay': True,
             'extendedProps': {
                 'text': memo_text,
                 'timestamp': memo_data['timestamp'],
                 'type': 'memo'
             }
             # 'color': '#ff9f89' # 필요시 동일 색상 지정
         }
        return jsonify(response_event), 201 # 201 Created

    except Exception as e:
        print(f"🚨 '/api/calendar/memos' [POST] 메모 저장 중 예외 발생: {e}")
        traceback.print_exc()

        # --- 롤백 로직 ---
        if requester_uid and memo_id and requester_uid in user_memory_storage and memo_id in user_memory_storage[requester_uid]:
            try:
                del user_memory_storage[requester_uid][memo_id]
                print(f"🧹 오류 발생으로 메모 롤백됨 (UID: {requester_uid}, Memo ID: {memo_id})")
            except KeyError:
                 print(f"🧹 롤백 시도 중 키 이미 없음 (Memo ID: {memo_id})")
            # 사용자 폴더가 비었으면 삭제 (선택적)
            if not user_memory_storage[requester_uid]:
                 try:
                     del user_memory_storage[requester_uid]
                     print(f"🧹 오류 발생으로 빈 사용자 폴더 삭제됨 (UID: {requester_uid})")
                 except KeyError:
                      pass

        return jsonify({"error": "메모 저장 중 서버 오류 발생", "detail": str(e)}), 500


@api_bp.route("/calendar/memos/<string:memo_id>", methods=['DELETE'])
def delete_calendar_memo(memo_id):
    """
    인증된 사용자의 특정 캘린더 메모를 삭제합니다.
    """
    print(f"--- '/api/calendar/memos/{memo_id}' [DELETE] 요청 처리 시작 ---")
    requester_uid = None
    global user_memory_storage, auth

    if not auth:
        print(f"🚨 /api/calendar/memos/{memo_id} [DELETE]: Firebase Auth object not available.")
        return jsonify({"error": "서버 인증 시스템 오류"}), 500

    # --- ▼▼▼ 인증 및 UID 얻기 (필수) ▼▼▼ ---
    auth_header = request.headers.get('Authorization')
    if not auth_header or not auth_header.startswith('Bearer '):
        print(f"🚨 /api/calendar/memos/{memo_id} [DELETE]: 인증 토큰 없음.")
        return jsonify({"error": "인증 토큰이 필요합니다."}), 401

    id_token = auth_header.split('Bearer ')[1]
    try:
        decoded_token = auth.verify_id_token(id_token)
        requester_uid = decoded_token.get('uid')
        if not requester_uid:
             print(f"🚨 /api/calendar/memos/{memo_id} [DELETE]: 유효 토큰이나 UID 정보 없음.")
             return jsonify({"error": "인증 토큰에 사용자 정보가 없습니다."}), 401
        print(f"ℹ️ /api/calendar/memos [DELETE] 요청 사용자 UID: {requester_uid}")
    except Exception as auth_err:
        print(f"🚨 /api/calendar/memos/{memo_id} [DELETE]: 토큰 검증 오류: {auth_err}")
        return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 401
    # --- ▲▲▲ 인증 및 UID 얻기 완료 ▲▲▲ ---

    try:
        # --- 메모 존재 및 소유권 확인 ---
        if requester_uid not in user_memory_storage:
            print(f"⚠️ 삭제 요청 실패: 사용자 (UID: {requester_uid}) 데이터 없음.")
            return jsonify({"error": "삭제할 메모를 찾을 수 없습니다."}), 404 # 사용자가 없음

        if memo_id not in user_memory_storage[requester_uid]:
            print(f"⚠️ 삭제 요청 실패: 사용자 (UID: {requester_uid})에게 해당 메모 (ID: {memo_id}) 없음.")
            return jsonify({"error": "삭제할 메모를 찾을 수 없습니다."}), 404 # 메모가 없음

        # (선택적) 삭제하려는 것이 정말 'memo' 타입인지 확인
        item_to_delete = user_memory_storage[requester_uid].get(memo_id)
        if not isinstance(item_to_delete, dict) or item_to_delete.get('type') != 'memo':
            print(f"🚨 삭제 요청 거부: 대상(ID: {memo_id})이 메모 타입이 아님 (Type: {item_to_delete.get('type')}).")
            return jsonify({"error": "잘못된 요청입니다. 메모만 삭제할 수 있습니다."}), 403 # Forbidden

        # --- 메모 삭제 ---
        del user_memory_storage[requester_uid][memo_id]
        print(f"✅ 메모 삭제 완료 (UID: {requester_uid}, Memo ID: {memo_id})")

        # (선택적) 사용자 폴더가 비었으면 삭제
        if not user_memory_storage[requester_uid]:
             try:
                 del user_memory_storage[requester_uid]
                 print(f"🧹 메모 삭제 후 빈 사용자 폴더 삭제됨 (UID: {requester_uid})")
             except KeyError:
                  pass # 이미 삭제되었을 수 있음

        return jsonify({"message": "메모가 성공적으로 삭제되었습니다."}), 200 # 또는 204 No Content

    except Exception as e:
        print(f"🚨 '/api/calendar/memos/{memo_id}' [DELETE] 메모 삭제 중 예외 발생: {e}")
        traceback.print_exc()
        # 롤백은 필요 없음 (삭제 작업이므로)
        return jsonify({"error": "메모 삭제 중 서버 오류 발생", "detail": str(e)}), 500


print("--- [API Routes] Routes defined (including calendar memo APIs) ---")