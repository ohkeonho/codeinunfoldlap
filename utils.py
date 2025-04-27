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
    if(key_topic=='고소장'):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
    elif(key_topic=='보충이유서'):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
    elif(key_topic=='검찰의견서'):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
    elif(key_topic=='합의서'):
        prompt = f"""
        넌 대한민국 최고의 변호사야 지금부터 '{key_topic}' 초안을 작성해줘야돼 이전 상담 내용정리하고 법률분석 한거랑 이번 상담 녹취록 그리고 PDF 내용을 기반으로 작성해.
        {all_document_text_parts}{previous_summary_text}{transcribed_text}
        """
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
            summary_text = summary_text.replace('##', '').replace('**', '').replace('*', '').strip()
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
    prompt = f"""내용정리하고 법률분석 해줘\n{text_to_summarize}"""
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
            summary_text = summary_text.replace('##', '').replace('**', '').replace('*', '').strip()
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

def find_previous_summary_content(name, phone, region):
    """이름/전화번호/지역으로 가장 최신 요약을 검색합니다."""
    print(f"⏳ [Util] 이전 요약 검색 시도: name={name}, phone={phone}, region={region}")
    found_summaries = []
    # User Memory 검색 (storage.py 변수 사용)
    if isinstance(user_memory_storage, dict):
        print(f"🔍 [Util] User Memory 검색 ({len(user_memory_storage)} UIDs)...")
        for uid, user_data_dict in user_memory_storage.items():
            if isinstance(user_data_dict, dict):
                 for storage_key, data_item in user_data_dict.items():
                     if isinstance(data_item, dict):
                         metadata = data_item.get('metadata', {})
                         if metadata.get('name') == name and metadata.get('phone') == phone and metadata.get('region') == region:
                             ts = data_item.get('timestamp'); smry = data_item.get('summary')
                             if ts and smry: found_summaries.append({'timestamp': ts, 'summary': smry, 'key': storage_key, 'storage': 'User', 'uid': uid})
    # Admin Memory 검색 (storage.py 변수 사용)
    if isinstance(admin_memory_storage, dict):
         print(f"🔍 [Util] Admin Memory 검색 ({len(admin_memory_storage)} items)...")
         for storage_key, data_item in admin_memory_storage.items():
            if isinstance(data_item, dict):
                 metadata = data_item.get('metadata', {})
                 if metadata.get('name') == name and metadata.get('phone') == phone and metadata.get('region') == region:
                     ts = data_item.get('timestamp'); smry = data_item.get('summary')
                     if ts and smry: found_summaries.append({'timestamp': ts, 'summary': smry, 'key': storage_key, 'storage': 'Admin'})

    if not found_summaries: print("ℹ️ [Util] 일치하는 이전 요약 없음."); return None
    # 정렬
    found_summaries.sort(key=lambda x: get_datetime_obj(x.get('timestamp')), reverse=True)
    latest = found_summaries[0]
    print(f"✅ [Util] 가장 최신 요약 발견 ({latest['storage']} Key: {latest['key']})")
    return latest.get('summary', '[요약 없음]')

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
            'original_uploader_email': metadata.get('uploader_email', 'N/A'), # 원본 업로더 이메일
            'key_topic': metadata.get('key_topic', 'N/A'),
            'uploader_uid': metadata.get('uploader_uid', 'N/A'),
            'sort_timestamp': get_datetime_obj(data_item.get('timestamp')) # 정렬용 datetime 객체
        }
    except Exception as e: print(f"🚨 [Util] 목록 항목 처리 오류 (Key: {storage_key}): {e}"); traceback.print_exc(); return None

def _create_summary_list(storage_to_search, requester_email, required_topic=None):
    """주어진 저장소에서 권한/토픽 필터링된 목록 생성"""
    summaries_list = []
    is_admin = requester_email in ADMIN_EMAILS # config에서 가져온 ADMIN_EMAILS 사용

    if not isinstance(storage_to_search, dict): return []

    # storage_to_search가 user_memory_storage일 경우 ({uid: {key:data}})
    for uid, user_data in storage_to_search.items():
        if isinstance(user_data, dict):
            for storage_key, data_item in user_data.items():
                processed_item = _process_summary_item(storage_key, data_item) # 내부 헬퍼 사용
                if processed_item:
                    item_topic = processed_item.get('key_topic')
                    target_client_email = processed_item.get('user_email')
                    original_uploader = processed_item.get('original_uploader_email')
                    topic_matches = (required_topic is None) or (item_topic == required_topic)
                    has_permission = False
                    if is_admin: has_permission = topic_matches
                    elif topic_matches:
                        if requester_email and (target_client_email == requester_email or original_uploader == requester_email):
                            has_permission = True
                    if has_permission:
                        summaries_list.append(processed_item) # 정렬용 키 포함하여 추가
        # else: # admin_memory_storage 등 다른 구조 처리 (현재는 user_memory_storage만 가정)

    # 시간순 정렬
    try:
        summaries_list.sort(key=lambda x: x.get('sort_timestamp', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
        for item in summaries_list: item.pop('sort_timestamp', None) # 정렬 후 임시 키 제거
    except Exception as sort_err: print(f"WARN [Util]: 목록 정렬 오류: {sort_err}")

    return summaries_list

# get_unique_filename, parse_filename 등 필요한 다른 헬퍼 함수들도 여기에 추가