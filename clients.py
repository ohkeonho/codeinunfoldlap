# clients.py
import requests
import json
from werkzeug.datastructures import FileStorage
# config 파일에서 Clova 설정값 가져오기
from config import invoke_url, secret

class ClovaSpeechClient:
    """Clova Speech API 요청을 위한 클라이언트 클래스"""
    def req_upload(self, file, completion, callback=None, userdata=None, forbiddens=None, boostings=None,
                   wordAlignment=True, fullText=True, diarization=True, sed=None):
        """음성 파일을 업로드하고 STT를 요청합니다."""
        request_body = {
            "language": "ko-KR", "completion": completion, "wordAlignment": wordAlignment,
            "fullText": fullText, "diarization": {"enable": diarization, "speakerCountMin": 2, "speakerCountMax": 2}
        }
        if callback: request_body['callback'] = callback
        if userdata: request_body['userdata'] = userdata
        if forbiddens: request_body['forbiddens'] = forbiddens
        if boostings: request_body['boostings'] = boostings
        if sed: request_body['sed'] = sed

        headers = {'Accept': 'application/json;UTF-8', 'X-CLOVASPEECH-API-KEY': secret} # config에서 가져온 secret
        media_data_to_send = None
        file_to_close = None

        try:
            if isinstance(file, str):
                print(f"DEBUG [ClovaClient]: 파일 경로에서 열기 시도: {file}")
                file_to_close = open(file, 'rb')
                media_data_to_send = file_to_close
            elif isinstance(file, FileStorage):
                 print(f"DEBUG [ClovaClient]: FileStorage 객체 사용: {file.filename}")
                 media_data_to_send = (file.filename, file.stream, file.content_type)
            else: raise TypeError(f"지원하지 않는 파일 타입: {type(file)}")

            files = {
                'media': media_data_to_send,
                'params': (None, json.dumps(request_body, ensure_ascii=False), 'application/json')
            }
            print(f"DEBUG [ClovaClient]: requests.post 호출 시작 (URL: {invoke_url + '/recognizer/upload'})") # config에서 가져온 invoke_url
            response = requests.post(headers=headers, url=invoke_url + '/recognizer/upload', files=files)
            print(f"DEBUG [ClovaClient]: requests.post 호출 완료 (Status: {response.status_code})")
            return response
        except Exception as e:
             print(f"🚨 ERROR [ClovaClient]: API 요청 중 오류 발생: {e}")
             raise e
        finally:
             if file_to_close is not None:
                 try:
                     print(f"DEBUG [ClovaClient]: 직접 열었던 파일 닫기: {getattr(file_to_close, 'name', 'N/A')}")
                     file_to_close.close()
                 except Exception as e_close:
                     print(f"🚨 WARNING [ClovaClient]: 파일 닫기 중 오류: {e_close}")

# 다른 외부 API 클라이언트 클래스가 있다면 여기에 추가