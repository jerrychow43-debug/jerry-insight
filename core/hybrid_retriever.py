class JaccardHybridRetriever:
    def __init__(self, chroma_collection):
        # 🔗 缝合点：接管你原本在主文件初始化好的 memory_collection 实例
        self.collection = chroma_collection

    def _jaccard_similarity(self, str1: str, str2: str) -> float:
        set1, set2 = set(str1), set(str2)
        intersection = set1.intersection(set2)
        union = set1.union(set2)
        return len(intersection) / len(union) if union else 0.0

    def retrieve_and_rerank(self, query: str, top_k: int = 3) -> str:
        """从 ChromaDB 召回数据，并用 Jaccard 算法对相关度进行重新打分排序"""
        try:
            db_res = self.collection.query(query_texts=[query], n_results=top_k * 2)
            if not db_res or not db_res['documents'] or not db_res['documents'][0]:
                return ""
            
            documents = db_res['documents'][0]
            metadatas = db_res['metadatas'][0] if db_res['metadatas'] else [{}] * len(documents)
            
            # 计算重排得分
            reranked_docs = []
            for doc, meta in zip(documents, metadatas):
                score = self._jaccard_similarity(query, doc)
                reranked_docs.append({"doc": doc, "meta": meta, "score": score})
            
            # 降序排列
            reranked_docs.sort(key=lambda x: x["score"], reverse=True)
            
            # 取前 top_k 个拼装返回
            final_context = []
            for item in reranked_docs[:top_k]:
                final_context.append(item["doc"])
                
            return "\n".join(final_context)
        except Exception as e:
            print(f"混合检索发生异常: {e}")
            return ""