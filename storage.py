# storage.py
# 메모리 기반 데이터 저장소 정의

print("--- [Storage] Initializing Storage ---")

# 사용자별 데이터를 저장하는 딕셔너리
# 키: 사용자 UID, 값: { storage_key: data_item } 형태의 딕셔너리
user_memory_storage = {}

# 관리자 관련 데이터 저장소 (필요한 경우)
# 키: storage_key, 값: data_item
admin_memory_storage = {}

# 필요하다면 다른 저장소 변수도 여기에 정의
# complaint_storage = {}
# ...

print(f"--- [Storage] Initialized storages (user: {len(user_memory_storage)}, admin: {len(admin_memory_storage)}) ---")