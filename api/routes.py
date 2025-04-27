# api/routes.py
from flask import Blueprint, request, jsonify
from firebase_admin import auth
import traceback
import os
import tempfile
from werkzeug.utils import secure_filename
from datetime import date, datetime, timezone

# --- 분리된 모듈에서 필요한 컴포넌트 임포트 ---
from config import PYDUB_AVAILABLE, AudioSegment # AudioSegment는 Mock 또는 실제 클래스
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

@api_bp.route("/record", methods=['POST'])
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

@api_bp.route("/admin/upload", methods=['POST'])
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
                try:print(f"🧹 (finally) 문서 임시 파일 삭제: {doc_path}")
                
                except OSError as e_rem: print(f"🚨 (finally) 문서 임시 파일 삭제 실패: {e_rem}")
        print(f"--- '/admin/upload' 요청 처리 완료 ---") # 처리 완료 로그 추가

# --- 목록 조회 라우트 ---
@api_bp.route("/complaints")
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

@api_bp.route("/supplementaries")
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


@api_bp.route("/prosecutor")
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

@api_bp.route("/agreements")
def list_agreements(): # 함수 이름을 list_agreements 로 변경
    """합의서 목록 반환 (인증 및 소유권/관리자/토픽 필터링)""" # 설명 수정
    id_token = None
    uploader_uid = None # 요청자 UID (로깅용)
    requester_email = '이메일 정보 없음' # 요청자 이메일

    # user_memory_storage 전역 변수 사용 명시 ▼▼▼
    global user_memory_storage

    # auth 객체가 초기화되어 있는지 확인합니다. (실제 auth 또는 Mock)
    if not auth:
        print("🚨 /api/agreements: Firebase Auth object not available.") # 로그 메시지 수정
        return jsonify({"error": "Server authentication system error"}), 500

    try:
        # --- ▼▼▼ ID 토큰 확인 및 요청자 UID, 이메일 얻기 (필수!) ▼▼▼ ---
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            print("🚨 /api/agreements: 인증 토큰 없음.") # 로그 메시지 수정
            # 목록 조회를 위해 인증 필수
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        id_token = auth_header.split('Bearer ')[1]
        try:
            decoded_token = auth.verify_id_token(id_token) # 토큰 검증
            uploader_uid = decoded_token.get('uid') # 요청자 UID (get 사용)
            requester_email = decoded_token.get('email', '이메일 정보 없음') # 요청자 이메일 추출

            if requester_email == '이메일 정보 없음':
                print("🚨 /api/agreements: 유효 토큰이나 이메일 정보 없음. 목록 필터링 불가.") # 로그 메시지 수정
                # 필터링을 위해 이메일 필수
                return jsonify({"error": "인증 토큰에 이메일 정보가 없습니다. 목록 필터링 불가."}), 401 # 또는 403

            print(f"ℹ️ /api/agreements 요청 사용자 UID: {uploader_uid}, Email: {requester_email}") # 로그 메시지 수정
            # 관리자 체크는 _create_summary_list 내부에서 이메일로 수행됩니다.

        except Exception as auth_err: # 토큰 검증/정보 추출 오류
            print(f"🚨 /api/agreements: 토큰 검증 오류: {auth_err}") # 로그 메시지 수정
            traceback.print_exc()
            is_invalid_token_error = isinstance(auth_err, auth.InvalidIdTokenError) if hasattr(auth, 'InvalidIdTokenError') else ("Invalid Token" in str(auth_err))
            error_status_code = 401 if is_invalid_token_error else 500
            return jsonify({"error": "인증 실패", "detail": str(auth_err)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 요청자 UID, 이메일 얻기 ▲▲▲ ---

        # --- 인증 통과 후 로직 수행 (데이터 필터링) ---
        print(f"--- '/api/agreements' 데이터 조회 시작 (요청자: {requester_email}) ---") # 로그 메시지 수정
        # user_memory_storage 전체에서 합의서 목록을 가져오되, 요청자의 이메일과 토픽("합의서")으로 필터링 ▼▼▼
        # _create_summary_list 함수는 다른 곳에 정의되어 있으며, user_memory_storage 구조를 탐색하고 필터링합니다.
        data = _create_summary_list(user_memory_storage, requester_email, required_topic="합의서") # <--- 조회 대상을 user_memory_storage로 변경하고 토픽을 "합의서"로 변경

        print(f"--- '/api/agreements' 처리 완료, {len(data)}개 항목 반환 ---") # 로그 메시지 수정
        return jsonify(data)

    except Exception as e:
        print(f"🚨 합의서 목록 생성 오류 (요청자: {requester_email}): {e}") # 로그 메시지 및 에러 메시지 수정
        traceback.print_exc()
        return jsonify({"error":"합의서 목록 생성 실패", "detail": str(e)}), 500 # 에러 메시지 수정

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


@api_bp.route("/events", methods=['GET'])
def get_calendar_events():
    """
    인증된 사용자의 user_memory_storage 데이터 항목들을 FullCalendar 이벤트 형식으로 반환합니다.
    인증 토큰이 필요하며, 해당 사용자의 데이터만 조회합니다.
    """
    print(f"--- '/api/events' 요청 처리 시작 ---")
    uploader_uid = None # 요청자의 UID (Firebase에서 검증 후 얻음)
    # user_memory_storage 전역 변수 사용 명시
    global user_memory_storage
    # Firebase Admin SDK의 auth 객체가 초기화되어 있는지 확인
    if not auth:
        print("🚨 /api/events: Firebase Auth object not available.")
        return jsonify({"error": "서버 인증 시스템 오류"}), 500

    try:
        # --- ▼▼▼ ID 토큰 확인 및 UID 얻기 (인증 필수) ▼▼▼ ---
        # Authorization 헤더에서 Bearer 토큰 추출
        auth_header = request.headers.get('Authorization')
        id_token = None
        if auth_header and auth_header.startswith('Bearer '):
            id_token = auth_header.split('Bearer ')[1]

        # 1. 토큰 존재 여부 확인 (없으면 401 Unauthorized)
        if not id_token:
            print("🚨 /api/events: Authorization 헤더 없거나 Bearer 토큰 아님. 인증 실패.")
            return jsonify({"error": "인증 토큰이 필요합니다."}), 401

        # 2. 토큰 검증 (실패 시 401 또는 500)
        try:
            decoded_token = auth.verify_id_token(id_token)
            uploader_uid = decoded_token['uid'] # <<< 로그인된 사용자의 UID 획득!
            requester_email = decoded_token.get('email', '이메일 정보 없음') # 이메일 정보 (로깅/확인용)
            print(f"ℹ️ /api/events 요청 사용자 UID: {uploader_uid}, Email: {requester_email}")

        except auth.InvalidIdTokenError as e:
            print(f"🚨 /api/events: 유효하지 않은 ID 토큰: {e}")
            # 유효하지 않은 토큰이므로 401 반환
            return jsonify({"error": "유효하지 않은 인증 토큰입니다.", "detail": str(e)}), 401
        except Exception as e: # 토큰 검증 중 다른 오류
            print(f"🚨 /api/events: 토큰 검증 오류: {e}")
            traceback.print_exc() # 서버 콘솔에 상세 오류 출력
            # 기타 검증 오류 시 500 반환
            return jsonify({"error": "토큰 검증 중 오류 발생", "detail": str(e)}), 500
        # --- ▲▲▲ ID 토큰 확인 및 UID 얻기 완료 ▲▲▲ ---

        # 이 시점 이후에는 uploader_uid 가 항상 유효한 값이어야 합니다.

        # --- 사용자 데이터 조회 및 FullCalendar 이벤트 형식으로 변환 ---
        calendar_events = []

        # user_memory_storage에서 현재 로그인된 사용자의 데이터만 가져옴
        user_specific_data = user_memory_storage.get(uploader_uid, {})

        print(f"ℹ️ UID '{uploader_uid}'의 데이터 {len(user_specific_data)}개 확인. 이벤트로 변환 시작.")

        # 각 데이터 항목을 순회하며 FullCalendar 이벤트 형식으로 변환
        for storage_key, data_item in user_specific_data.items():
            try:
                # data_item이 유효한 딕셔너리인지 확인
                if not isinstance(data_item, dict):
                    print(f"WARN: UID '{uploader_uid}'의 저장소에 유효하지 않은 항목 스킵: {storage_key}")
                    continue

                # 필요한 데이터 추출 (None 방지)
                metadata = data_item.get('metadata', {})
                timestamp_iso = data_item.get('timestamp') # ISO 8601 형식 시간 문자열
                # source = data_item.get('source', 'unknown') # 필요시 이벤트 속성에 추가 가능

                # FullCalendar 이벤트의 title 생성
                item_topic = metadata.get('key_topic', '자료') # 문서 종류 (예: 고소장, 보충이유서)
                item_name = metadata.get('name', '정보없음') # 의뢰인 이름
                event_title = f"[{item_topic}] {item_name}" # 예: "[고소장] 김철수" 또는 "[자료] 홍길동"

                # FullCalendar 이벤트의 start 시간 (timestamp 사용)
                event_start = None
                if timestamp_iso:
                    try:
                        # ISO 8601 문자열을 datetime 객체로 파싱 (선택적, FullCalendar는 ISO 문자열도 받음)
                        # dt_object = datetime.fromisoformat(timestamp_iso)
                        # event_start = dt_object.isoformat() # 다시 ISO 문자열로 (시간대 정보 유지)
                        # FullCalendar는 ISO 8601 문자열을 start 속성으로 잘 처리하므로 그대로 사용
                        event_start = timestamp_iso
                    except ValueError:
                        print(f"WARN: 유효하지 않은 타임스탬프 형식 (키: {storage_key}): {timestamp_iso}")
                        # 유효하지 않으면 이 이벤트는 추가하지 않거나 start를 None으로 설정
                        continue # 유효한 start 시간이 없으면 이벤트 목록에 추가하지 않음

                # FullCalendar 이벤트 객체 생성
                event_object = {
                    'id': storage_key, # FullCalendar는 이벤트 ID로 사용
                    'title': event_title,
                    'start': event_start, # ISO 8601 형식 문자열
                    # 'end': '...', # 종료 시간이 있다면 추가 (없으면 한 시점 이벤트)
                    # 'allDay': True/False, # 종일 이벤트 여부 (start 시간만 있다면 True로 간주될 수 있음)
                    # extendedProps에 상세 정보 저장 (클라이언트 eventClick 시 활용)
                    'extendedProps': {
                        'name': metadata.get('name', 'N/A'),
                        'phone': metadata.get('phone', 'N/A'),
                        'region': metadata.get('region', 'N/A'),
                        'source': data_item.get('source', 'unknown'),
                        'user_email': metadata.get('user_email', requester_email), # 대상 의뢰인 이메일
                        'uploader_email': metadata.get('uploader_email', requester_email), # 업로더 이메일 (admin 업로드용)
                        'key_topic': item_topic,
                        'summary_preview': data_item.get('summary', '')[:100] + '...' # 요약 미리보기 (전체 요약은 너무 길 수 있음)
                    }
                }

                # 생성된 이벤트 객체를 리스트에 추가
                calendar_events.append(event_object)

            except Exception as item_e:
                # 개별 항목 처리 중 오류 발생 시 로깅하고 계속 진행
                print(f"🚨 UID '{uploader_uid}'의 항목 '{storage_key}' 처리 중 오류 발생: {item_e}")
                traceback.print_exc() # 오류 상세 정보 출력 (개발 중 유용)
                # 이 항목은 calendar_events 리스트에 추가되지 않음

        # --- 이벤트 목록 JSON 응답 ---
        print(f"--- '/api/events' 처리 완료. 총 {len(calendar_events)}개 이벤트 반환 ---")
        return jsonify(calendar_events), 200 # 성공 시 200 OK 상태 코드와 함께 이벤트 목록 반환

    except Exception as e:
        # 인증 오류 외 다른 예상치 못한 오류 처리
        print(f"🚨 '/api/events' 요청 처리 중 예외 발생: {e}")
        traceback.print_exc() # 서버 콘솔에 전체 스택 트레이스 출력
        return jsonify({"error": "이벤트 데이터 생성 중 서버 오류 발생", "detail": str(e)}), 500
# 나머지 기존 Flask 라우트 및 코드들 ...
# if __name__ == '__main__':
#     app.run(...)

print("--- [API Routes] Routes defined ---")