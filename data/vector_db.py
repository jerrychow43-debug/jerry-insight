import chromadb
from chromadb.utils import embedding_functions

# 这里的路径改为 data 目录下
client = chromadb.PersistentClient(path="./data/jerry_vector_db")
default_ef = embedding_functions.DefaultEmbeddingFunction()
collection = client.get_or_create_collection(name="jerry_info", embedding_function=default_ef)

def get_jerry_profile():
    # 模拟博主说的“混合检索”：直接强制命中核心画像
    res = collection.query(query_texts=["Jerry 的月薪和雷点"], n_results=1)
    return res['documents'][0][0] if res['documents'] else "暂无个人档案"