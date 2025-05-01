# utils.py
import os
import re
import io
import traceback
from datetime import datetime, timezone
# 필요한 설정, 저장소, 라이브러리 클래스 등을 새 파일들에서 가져옴
from config import (
    gemini_model, GOOGLE_API_KEY_PATH, VISION_AVAILABLE, PYPDF2_AVAILABLE, ADMIN_EMAILS,
    vision, PdfReader, google_exceptions, AudioSegment # Mock 또는 실제 클래스/객체
)
from storage import user_memory_storage, admin_memory_storage

# --- 모든 헬퍼 함수 정의 ---

def summarize_with_context(transcribed_text, all_document_text_parts, key_topic, previous_summary_text):
    """Gemini를 사용하여 문맥 기반 요약/분석을 수행합니다."""
    if not gemini_model: return "[오류] Gemini 모델이 설정되지 않았습니다."
    if not hasattr(gemini_model, 'generate_content'): return "[오류] Gemini 모델 초기화 오류입니다."
    if not (transcribed_text or all_document_text_parts or previous_summary_text):
        return "[오류] 분석할 내용(녹취록, PDF, 이전 요약)이 없습니다."

    # 프롬프트 구성
    """ 관리자 업로드 상세 분석용 함수 """
    if not gemini_model: return "Gemini API 미설정"
    if not hasattr(gemini_model, 'generate_content'): return "Gemini 모델 초기화 오류"
    if not transcribed_text and not all_document_text_parts and not previous_summary_text: return "분석할 내용(녹취록, PDF, 이전 요약)이 전혀 없습니다."
    # prompt = f"""
    # 넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 내용정리하고 법률분석 하고 PDF 내용을 참고해서 작성해.대답하지 말고 {key_topic} 초안만 보여줘
    # {all_document_text_parts}{previous_summary_text}{transcribed_text}
    #     """
    print(f"--- 디버깅: key_topic의 값: {key_topic}") # key_topic도 잘 넘어오는지 확인
    print(f"--- 디버깅: previous_summary_text의 길이: {len(previous_summary_text) if previous_summary_text else 0}")
    # 이전 상담 내용이 길 수 있으니 앞부분만 확인해도 좋습니다.
    print(f"--- 디버깅: previous_summary_text (앞 500자): {str(previous_summary_text)[:500] if previous_summary_text else '비어있음'}")
    print(f"--- 디버깅: all_document_text_parts의 길이: {len(all_document_text_parts) if all_document_text_parts else 0}")
    print(f"--- 디버깅: transcribed_text의 길이: {len(transcribed_text) if transcribed_text else 0}")

    prompt = f"""
    당신은 대한민국 최고의 변호사입니다.

    아래에 제공된 '이전 상담 내용 및 분석', '이번 상담 녹취록 내용', '관련 PDF 문서 내용'을 종합적으로 참고하고,
    또 그것에 맞는 사실관계(개요) 부분에 주석 및 판례 부분이 들어가게 하고 '{key_topic}'을 전문적이고 완성도 높게 작성해주세요.

    문서 작성 외에 다른 설명이나 서두/결론 문구 없이, 오직 '{key_topic}' 문서 내용만 제공해주세요.

    --- 이전 상담 내용 및 분석 ---
    {previous_summary_text if previous_summary_text else "제공된 이전 상담 내용 및 분석이 없습니다."}

    --- 이번 상담 녹취록 내용 ---
    {transcribed_text if transcribed_text else "제공된 이번 상담 녹취록 내용이 없습니다."}

    --- 관련 PDF 문서 내용 ---
    {all_document_text_parts if all_document_text_parts else "제공된 관련 PDF 문서 내용이 없습니다."}

    """
    # prompt = f"""
    # 넌 대한민국 최고의 변호사야 지금부터 {key_topic} 작성해줘야돼. 그리고 이번 상담 녹취록 내용정리하고 법률분석해주고 이전 상담내용이랑 PDF 내용을 참고해서 {key_topic}작성해.대답하지 말고 {key_topic}만 보여줘
    # 이번상담 녹취록:{transcribed_text}이전 상담내용:{previous_summary_text} PDF:{all_document_text_parts}
    #     """
    try:
        print(f"⏳ [Util] Gemini '{key_topic}' 분석 요청...")
        response = gemini_model.generate_content(prompt) # 필요시 config, safety 설정 추가
        print("✅ [Util] Gemini 응답 받음.")
        summary_text = None
        try:
            summary_text = response.text
        except ValueError as ve:
            print(f"⚠️ [Util] Gemini 응답 텍스트 접근 불가 (Safety Block?): {ve}")
            if hasattr(response, 'prompt_feedback'): print(f"   [Util] Prompt Feedback: {response.prompt_feedback}")
            summary_text = f"[오류] Gemini 콘텐츠 생성 실패: {ve}"
        except AttributeError:
             if hasattr(response, 'candidates') and response.candidates:
                 try: summary_text = response.candidates[0].content.parts[0].text
                 except Exception as e_cand: print(f"⚠️ [Util] candidates 텍스트 추출 실패: {e_cand}"); summary_text = "[오류] 응답 구조에서 텍스트 추출 실패"
        except Exception as e_resp: print(f"🚨 [Util] 응답 처리 중 오류: {e_resp}"); summary_text = f"[오류] 응답 처리 오류: {e_resp}"

        if summary_text and not summary_text.startswith("[오류]"):
            summary_text = summary_text.replace('##', '').replace('**', '').replace('*', '').replace('/','').strip()
            return summary_text
        elif summary_text: return summary_text
        else: print(f"⚠️ [Util] 유효 텍스트 못 받음. 응답: {response}"); return "[오류] Gemini 분석 결과 없음."
    except Exception as e:
        print(f"🚨 [Util] Gemini API 호출 중 오류 ('{key_topic}'): {e}")
        print(traceback.format_exc())
        error_message = f"Gemini 분석 중 오류: {type(e).__name__}"
        error_str = str(e).lower();
        if "api key" in error_str or "permission denied" in error_str: error_message += " (API 키/권한 문제)"
        elif "quota" in error_str: error_message += " (API 할당량 초과)"
        elif " deadline exceeded" in error_str: error_message += " (요청 시간 초과)"
        elif "resource exhausted" in error_str: error_message += " (리소스 부족)"
        elif "model not found" in error_str: error_message += " (모델 이름 확인 필요)"
        elif "safety" in error_str: error_message += " (콘텐츠 안전 문제로 차단됨)"
        return error_message

def summarize_text_with_gemini(text_to_summarize):
    """Gemini를 사용하여 일반 텍스트 요약 및 법률 분석을 수행합니다."""
    if not gemini_model: return "[오류] Gemini 모델 미설정"
    if not hasattr(gemini_model, 'generate_content'): return "[오류] Gemini 모델 초기화 오류"
    if not text_to_summarize: return "[정보] 요약할 텍스트 없음"
    prompt = f"""대답은 하지 말고 내용정리하고 법률분석하고 사실관계(개요)만들어줘. 그리고 법률분석 부분에 주석 및 판례 부분이 들어가게 하고 문서 작성 외에 다른 설명이나 서두/결론 문구 없이 해줘.\n{text_to_summarize}"""
    try:
        print("⏳ [Util] Gemini 요약 요청...")
        response = gemini_model.generate_content(prompt)
        print("✅ [Util] Gemini 응답 받음.")
        summary_text = None
        try: summary_text = response.text
        except ValueError as ve: print(f"⚠️ [Util] Gemini 요약 응답 접근 불가: {ve}"); summary_text = f"[오류] 요약 생성 실패: {ve}"
        except AttributeError:
            if hasattr(response, 'candidates') and response.candidates:
                try: summary_text = response.candidates[0].content.parts[0].text
                except: summary_text = "[오류] 응답 구조에서 요약 추출 실패"
        except Exception as e_resp: summary_text = f"[오류] 응답 처리 오류: {e_resp}"

        if summary_text and not summary_text.startswith("[오류]"):
            summary_text = summary_text.replace('##', '').replace('**', '').replace('*', '').replace('/','').strip()
            return summary_text
        elif summary_text: return summary_text
        else: print(f"⚠️ [Util] Gemini 요약 결과 없음. 응답: {response}"); return "[오류] Gemini 요약 결과 없음."
    except Exception as e:
        print(f"🚨 [Util] Gemini API 호출 중 오류 (요약): {e}")
        print(traceback.format_exc())
        error_message = f"Gemini 요약 중 오류: {type(e).__name__}"
        error_str = str(e).lower()
        if "api key" in error_str: error_message += " (API 키 문제)"
        elif "quota" in error_str: error_message += " (할당량 초과)"
        # ... 기타 오류 처리 ...
        return error_message

def sanitize_filename(filename):
    """파일 이름에서 유효하지 않은 문자를 제거합니다."""
    if not filename: return "untitled"
    base_name = os.path.basename(str(filename))
    sanitized = re.sub(r'[\\/*?:"<>|]', "_", base_name)
    sanitized = sanitized.strip(' .')
    return sanitized if sanitized else "sanitized_filename"

def extract_text_from_file(original_filename, file_path=None, file_bytes=None):
    """파일 경로 또는 바이트에서 텍스트를 추출합니다 (PDF, 이미지 OCR)."""
    print(f"📄 [Util] 텍스트 추출 시작: {original_filename}")
    if not file_path and not file_bytes: return "[오류] 파일 경로 또는 내용 없음"
    if not original_filename: return "[오류] 원본 파일명 없음"
    try: _, file_extension = os.path.splitext(original_filename); file_extension = file_extension.lower()
    except Exception as e: return f"[오류] 확장자 확인 불가: {e}"
    content_to_process = None
    if file_path and os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f: content_to_process = f.read()
            print(f"   - [Util] 파일 읽기 완료: {len(content_to_process)} bytes")
        except Exception as read_err: return f"[오류] 파일 읽기 실패: {read_err}"
    elif file_bytes:
        content_to_process = file_bytes
        print(f"   - [Util] 바이트 내용 사용: {len(content_to_process)} bytes")
    else: return f"[오류] 유효 파일/내용 없음: {original_filename}"

    if file_extension == '.pdf':
        if not PYPDF2_AVAILABLE: return "[오류] PDF 라이브러리 없음"
        text = ""
        try:
            reader = PdfReader(io.BytesIO(content_to_process)) # config에서 import
            if reader.is_encrypted:
                 try:
                     if reader.decrypt('') == 0: return f"[오류] 암호화된 PDF: {original_filename}"
                     else: print(f"   - [Util] PDF 복호화 성공/불필요")
                 except Exception as decrypt_err: return f"[오류] PDF 복호화 실패: {decrypt_err}"
            for i, page in enumerate(reader.pages):
                 try: page_text = page.extract_text(); text += (page_text + "\n") if page_text else ""
                 except Exception as page_err: text += f"[페이지 {i+1} 추출 오류: {page_err}]\n"
            extracted_text = text.strip()
            print(f"   - [Util] PDF 텍스트 추출 완료")
            return extracted_text if extracted_text else "[정보] PDF 텍스트 없음"
        except Exception as e: print(f"🚨[Util] PDF 처리 오류: {e}"); traceback.print_exc(); return f"[오류] PDF 처리 예외: {e}"

    elif file_extension in ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.gif', '.webp', '.ico']:
        if not VISION_AVAILABLE: return "[오류] Vision 라이브러리 없음"
        if not GOOGLE_API_KEY_PATH or not os.path.exists(GOOGLE_API_KEY_PATH): return "[오류] Vision API 키 파일 문제"
        try:
            print(f"   - [Util] Vision API 호출 시작")
            client = vision.ImageAnnotatorClient.from_service_account_file(GOOGLE_API_KEY_PATH) # config에서 import
            image = vision.Image(content=content_to_process)
            response = client.document_text_detection(image=image)
            if response.error.message: return f"[오류] Vision API: {response.error.message}"
            if response.full_text_annotation:
                 extracted_text = response.full_text_annotation.text.strip()
                 print(f"   - [Util] Vision API 텍스트 추출 완료")
                 return extracted_text if extracted_text else "[정보] 이미지 텍스트 없음"
            else: return "[정보] Vision API가 텍스트를 찾지 못함"
        except google_exceptions.GoogleAPIError as e: return f"[오류] Vision API 통신 오류: {e}" # config에서 import
        except Exception as e: print(f"🚨[Util] 이미지 처리 오류: {e}"); traceback.print_exc(); return f"[오류] 이미지 처리 예외: {e}"

    else: return f"[오류] 지원하지 않는 파일 형식: {file_extension}"

# user_memory_storage, admin_memory_storage, get_datetime_obj 등
# 필요한 전역 변수 또는 함수들이 import 되어 있어야 합니다.

def find_previous_summary_content(uploader_uid, name, phone, region):
    """
    주어진 업로더 UID의 user_memory_storage에서
    이름/전화번호/지역에 해당하는 가장 최신 요약을 검색합니다.
    admin_memory_storage는 검색하지 않습니다 (admin_upload 로직에 맞춤).
    """
    print(f"⏳ [Util] 이전 요약 검색 시도: Uploader UID={uploader_uid}, name={name}, phone={phone}, region={region}")
    found_summaries = []

    # ⚠️ 핵심: uploader_uid에 해당하는 user_memory_storage 내부만 검색
    if isinstance(user_memory_storage, dict) and uploader_uid in user_memory_storage:
        user_data_dict = user_memory_storage[uploader_uid]
        print(f"🔍 [Util] Uploader UID {uploader_uid}의 User Memory 검색 ({len(user_data_dict)} 항목)...")

        if isinstance(user_data_dict, dict):
            for storage_key, data_item in user_data_dict.items():
                if isinstance(data_item, dict):
                    metadata = data_item.get('metadata', {})
                    # 대상 의뢰인 정보 일치 여부 확인
                    # 검색 시 clientEmail도 기준으로 삼는 것이 더 정확할 수 있습니다.
                    # 현재는 name, phone, region만 사용합니다.
                    if metadata.get('name') == name and metadata.get('phone') == phone and metadata.get('region') == region:
                         ts = data_item.get('timestamp'); smry = data_item.get('summary')
                         # '분석 완료' 상태인 데이터만 가져오거나, 상태와 무관하게 가져올지 결정 필요
                         # 여기서는 상태 무관하게 가져오는 예시
                         if ts and smry:
                             # 이전 요약 검색 시에는 files_content는 제외하고 summary만 필요
                             # storage_key는 그대로 유지
                             found_summaries.append({'timestamp': ts, 'summary': smry, 'key': storage_key, 'storage': 'User', 'uid': uploader_uid}) # UID 정보 포함

    # Admin Memory 검색 로직 제거 - admin_upload는 user_memory_storage에 저장하므로 일관성 유지
    # 만약 admin_memory_storage에서도 검색이 필요하다면 별도의 로직 추가 고려

    if not found_summaries:
        print(f"ℹ️ [Util] Uploader UID {uploader_uid}의 저장소에서 일치하는 이전 요약 없음.")
        return None

    # 정렬 (가장 최신 데이터 찾기)
    try:
        found_summaries.sort(key=lambda x: get_datetime_obj(x.get('timestamp')), reverse=True)
        latest = found_summaries[0]
        print(f"✅ [Util] Uploader UID {uploader_uid}의 저장소에서 가장 최신 요약 발견 (Key: {latest['key']})")
        return latest.get('summary', '[요약 없음]')
    except Exception as sort_err:
        # 타임스탬프 형식 오류 등으로 정렬 실패 시
        print(f"🚨 [Util] 이전 요약 정렬 중 오류 발생: {sort_err}")
        # 오류 발생 시 요약 반환 여부 결정 (예: 첫 번째 찾은 요약 반환 또는 None 반환)
        # 여기서는 오류 발생 시에도 일단 찾은 첫 번째 요약 반환 (안전성을 위해 None 반환 고려 가능)
        if found_summaries:
             print("⚠️ [Util] 정렬 오류로 인해 첫 번째 찾은 요약 반환.")
             return found_summaries[0].get('summary', '[요약 없음 - 정렬 오류]')
        return None


def get_datetime_obj(iso_str):
    """ISO 문자열 -> datetime 객체 변환 (정렬용)"""
    if not iso_str: return datetime.min.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(iso_str); return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except: return datetime.min.replace(tzinfo=timezone.utc)

def format_timestamp(iso_str):
    """ISO 문자열 -> YYYY-MM-DD HH:MM:SS 형식 변환"""
    if not iso_str: return "N/A"
    try: return get_datetime_obj(iso_str).strftime('%Y-%m-%d %H:%M:%S')
    except: return str(iso_str)

def _process_summary_item(storage_key, data_item):
    """단일 항목을 목록 API 형식으로 변환"""
    try:
        if not isinstance(data_item, dict): return None
        metadata = data_item.get('metadata', {})
        # format_timestamp, get_datetime_obj는 이 파일 내에 정의됨
        return {
            'storage_key': storage_key, 'name': metadata.get('name', 'N/A'),
            'phone': metadata.get('phone', 'N/A'), 'region': metadata.get('region', 'N/A'),
            'date_created': format_timestamp(data_item.get('timestamp')),
            'source': data_item.get('source', 'unknown'), 'summary': data_item.get('summary', '[요약 없음]'),
            'user_email': metadata.get('email', 'N/A'), # 대상 의뢰인 이메일
            'original_uploader_email': metadata.get('uploader_email', 'N/A' ), # 원본 업로더 이메일
            'topic': metadata.get('key_topic', '종류 정보 없음'),
            'uploader_uid': metadata.get('uploader_uid', 'N/A'),
            'sort_timestamp': get_datetime_obj(data_item.get('timestamp')) # 정렬용 datetime 객체
        }
    except Exception as e: print(f"🚨 [Util] 목록 항목 처리 오류 (Key: {storage_key}): {e}"); traceback.print_exc(); return None

def _create_summary_list(storage_to_search, requester_email, required_topic=None, client_identifier=None, target_uid=None):
    """
    주어진 저장소에서 특정 사용자(target_uid), 토픽, 클라이언트로 필터링된 목록 생성.
    target_uid가 None이면 (관리자 전체 조회 등) 모든 사용자 데이터를 고려합니다.
    """
    summaries_list = []
    # 이 함수 내에서는 ADMIN_EMAILS를 이용한 직접적인 관리자 권한 필터링은 수행하지 않습니다.
    # 권한 필터링은 target_uid를 설정하는 상위 엔드포인트의 책임입니다.
    # is_requester_admin = requester_email in ADMIN_EMAILS # 이 변수는 여기서 직접 사용되지 않습니다.


    print(f"DEBUG [_create_summary_list]: Called with requester_email={requester_email}, required_topic={required_topic}, client_identifier='{client_identifier}', target_uid={target_uid}")

    if not isinstance(storage_to_search, dict):
        print("WARN [_create_summary_list]: storage_to_search is not a dict.")
        return []

    # --- ▼▼▼ 타겟 사용자 데이터 선택 로직 ▼▼▼ ---
    users_to_process_data = {}
    if target_uid is not None:
        # target_uid가 지정되면 해당 사용자의 데이터만 가져와 처리
        user_data_for_target = storage_to_search.get(target_uid, {})
        if user_data_for_target:
            users_to_process_data[target_uid] = user_data_for_target
            print(f"DEBUG [_create_summary_list]: Processing data for target_uid: {target_uid}")
        else:
             print(f"DEBUG [_create_summary_list]: target_uid {target_uid} not found in storage_to_search or has no data.")
             # 해당 사용자의 데이터가 없으면 users_to_process_data가 비어있게 되어 아래 루프는 돌지 않습니다.
    else:
        # target_uid가 지정되지 않으면 (예: 관리자 전체 조회 시),
        # storage_to_search 전체를 처리합니다.
        # NOTE: 실제 관리자 전체 조회 엔드포인트에서는 이 함수 호출 전에 관리자 권한을 확인해야 합니다.
        users_to_process_data = storage_to_search
        print(f"DEBUG [_create_summary_list]: No target_uid specified. Processing data for all users.")


    # --- ▼▼▼ 데이터 항목들을 순회하며 필터링 시작 ▼▼▼ ---
    # users_to_process_data는 이제 {uid: user_data_dict} 형태 또는 비어있는 딕셔너리
    for uid_in_storage, user_data_dict in users_to_process_data.items(): # 선택된 사용자(들)의 UID를 순회
        if not isinstance(user_data_dict, dict):
             print(f"WARN [_create_summary_list]: user_data_dict for UID {uid_in_storage} is not a dict. Skipping.")
             continue # 유효하지 않은 형식은 스킵

        for storage_key, data_item in user_data_dict.items(): # 해당 사용자의 문서 항목을 순회
            if not isinstance(data_item, dict):
                print(f"WARN [_create_summary_list]: data_item for key {storage_key} (UID {uid_in_storage}) is not a dict. Skipping.")
                continue

            # --- 항목의 클라이언트 식별 정보 추출 및 정규화 (기존 로직 유지) ---
            item_metadata = data_item.get('metadata', {})
            item_client_name_raw = item_metadata.get('name', '')
            item_client_phone_raw = item_metadata.get('phone', '')
            item_client_email_raw = item_metadata.get('email', item_metadata.get('user_email', ''))

            item_client_name_norm = item_client_name_raw.strip()
            # 전화번호는 하이픈을 유지하고 앞뒤 공백만 제거합니다.
            item_client_phone_for_identifier = item_client_phone_raw.strip()
            # 이메일 부분은 요청된 client_identifier에 없으므로 포함하지 않습니다.
            calculated_identifier = f"{item_client_name_norm}|{item_client_phone_for_identifier}|" # 계산된 클라이언트 식별자

            # ▼▼▼ 디버그 로그 추가: 계산될 identifier와 요청된 identifier 확인 ▼▼▼
            # 이 로그를 통해 불일치 여부를 확인할 수 있습니다.
            print(f"DEBUG [_create_summary_list]: Item Key: {storage_key}, Calculated ID: '{calculated_identifier}', Requested ID: '{client_identifier}'")
            # ▲▲▲ 디버그 로그 추가 ▲▲▲


            # 클라이언트 식별 정보 불충분 체크 (기존 로직)
            if not item_client_name_norm and not item_client_phone_for_identifier and not item_client_email_raw.strip(): # 이메일도 확인
                 print(f"WARN [_create_summary_list]: Skipping item {storage_key} - Insufficient client info.")
                 continue

            # --- ▼▼▼ 필터링 조건 (토픽 및 client_identifier 일치 확인) ▼▼▼ ---
            # 이 함수는 이미 target_uid로 데이터 대상을 한정했거나 전체를 대상으로 하고 있으므로,
            # 여기서 직접적인 '권한' 체크 (예: 이메일 일치 또는 관리자 여부)는 필요하지 않습니다.
            # 권한 체크는 이 함수를 호출하는 상위 엔드포인트에서 target_uid를 올바르게 설정하는 것으로 대신합니다.

            # 토픽 일치 여부 확인 (기존 로직)
            item_topic = item_metadata.get('key_topic')
            topic_matches = (required_topic is None) or (item_topic == required_topic)

            # 클라이언트 식별자 일치 여부 확인 (계산된 identifier와 요청된 identifier 비교)
            client_identifier_matches = (client_identifier is None) or (calculated_identifier == client_identifier)

            # _process_summary_item 호출 (필터 통과 여부와 무관하게 데이터 처리는 시도)
            processed_item = _process_summary_item(storage_key, data_item)

            if not processed_item:
                 print(f"WARN [_create_summary_list]: _process_summary_item returned None for item {storage_key}. Skipping.")
                 continue


            # --- ▼▼▼ 최종 필터링 통과 항목 추가 ▼▼▼ ---
            # 토픽 필터와 클라이언트 식별자 필터 모두 통과 시 추가합니다.
            # (권한 체크는 target_uid로 이미 걸러졌거나 상위 엔드포인트에서 처리된다고 가정)
            if topic_matches and client_identifier_matches:
                 print(f"DEBUG [_create_summary_list]: Including item {storage_key} - Passed topic and client identifier filters.") # 최종 통과 항목 로그
                 summaries_list.append(processed_item)
            else:
                 # 필터 실패 항목은 건너뜁니다.
                 print(f"DEBUG [_create_summary_list]: Skipping item {storage_key} - Failed filters: topic_matches={topic_matches}, client_identifier_matches={client_identifier_matches}.")
                 pass # 필터 실패 항목은 건너뛰지 않고 로그를 남깁니다.


    # --- ▼▼▼ 시간순 정렬 (기존 로직 유지) ▼▼▼ ---
    try:
        def get_sort_key(item):
             timestamp_val = item.get('date_created') or item.get('timestamp')
             if isinstance(timestamp_val, str):
                 try:
                     return datetime.fromisoformat(timestamp_val.replace('Z', '+00:00'))
                 except ValueError:
                     print(f"WARN [_create_summary_list]: Failed to parse date string for sorting: {timestamp_val}")
                     return datetime.min.replace(tzinfo=timezone.utc)
             return datetime.min.replace(tzinfo=timezone.utc)

        summaries_list.sort(key=get_sort_key, reverse=True)
        print(f"DEBUG [_create_summary_list]: Results sorted by date.")

    except Exception as sort_err:
          print(f"WARN [_create_summary_list]: Document list sorting error: {sort_err}")
          traceback.print_exc()


    print(f"DEBUG [_create_summary_list]: Returning {len(summaries_list)} items.")
    return summaries_list

def is_path_safe(file_path):
    """주어진 파일 경로가 BASE_TEMP_DIR 내부에 있는지 안전하게 확인합니다."""
    if not file_path:
        return False
    try:
        # 경로를 절대 경로로 변환
        abs_file_path = os.path.abspath(file_path)
        abs_base_temp_dir = os.path.abspath(BASE_TEMP_DIR)

        # 파일 경로가 BASE_TEMP_DIR 하위 경로로 시작하는지 확인
        # os.path.commonprefix 사용 시 /tmp/../etc/passwd 같은 경로 공격 방어
        return os.path.commonprefix([abs_file_path, abs_base_temp_dir]) == abs_base_temp_dir
    except Exception as e:
        print(f"🚨 안전 경로 검증 오류: {e}")
        return False