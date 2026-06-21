這是一份為您量身打造的「私有化地端推理式 RAG (On-Premise PageIndex) 系統開發規格書」。本文件整合了前面所有關於架構、資料流、儲存設計以及檢索策略的討論，供您與開發團隊直接進行系統實作。

TXC 企業內部知識管理 (KM) 系統：私有化地端推理式 RAG 開發規格書
1. 系統概述 (System Overview)
本系統旨在解決傳統 RAG 因文件切碎（Chunking）導致的語意斷裂與長文件複雜邏輯推理能力不足的痛點。系統採用 「混合型 Agentic RAG」 架構：

大範圍粗篩：利用地端向量資料庫（Vector DB）進行跨文件海選。

微觀精準定位：參考 PageIndex 的設計理念，預先為單一文件建立 JSON 樹狀大綱索引 (TOC Tree)，並由地端 LLM Agent 進行多輪目錄導航，精準定位原始內文的起迄頁碼。

資訊安全：全系統 100% 地端部署（On-Premise），資料不外流，無雲端 SaaS 訂閱費用。

2. 系統架構與技術堆疊 (Tech Stack)
2.1 核心元件
文件解析引擎：MinerU (Magic-PDF) — 用於高精度 PDF 轉 Markdown，支援複雜表格與公式解析。

向量資料庫：Qdrant  (Docker 地端部署) — 用於儲存文件摘要向量。

關聯式資料庫：PostgreSQL (支援 JSONB) — 用於儲存文件樹狀結構與逐頁 Raw 內文。

地端推論引擎：litellm — 負責運行開源大模型。

模型選擇：Qwen3.5-27b (需具備優異的繁體中文理解與 Structured Outputs 結構化輸出能力)。

Agent 協調框架：Agno (原 Phidata)  — 用於實作意圖路由與決策導航。

1. 資料寫入管線 (Data Ingestion Pipeline)
當使用者上傳一份 PDF 文件時，後台非同步 Worker（如 Celery）必須執行以下管線：

[上傳 PDF] 支援單一文件或批次文件
   │
   ▼
[MinerU 解析] ───> 產出帶有頁碼標籤的 Raw Markdown
   │
   ├───> 提取「純標題大綱」 ──> [地端 LLM] ──> 生成 JSON 樹狀目錄 ──> 存入 PostgreSQL
   │
   ├───> 依頁碼切分內文 ───────────────────────────────────────> 存入 PostgreSQL (逐頁)
   │
   └───> 提取整份文件摘要 ───> [Embedding, 混合向量+BM25] ────────────────────> 存入 Vector DB
3.1 步驟一：MinerU 檔案解析
調用 MinerU 命令列工具將 PDF 轉為標準 Markdown：

Bash
magic-pdf -i "TXC_SOP_2026.pdf" -o "./output_dir" -m json
關鍵輸出要求：產出的 Markdown 必須包含清晰的標題階層（#, ##, ###）以及精確的頁碼標籤（例如：``）。

3.2 步驟二：關聯式資料庫儲存設計 (PostgreSQL)
開發團隊需建立以下兩張核心資料表：

表 A：km_documents (儲存文件大綱與 PageIndex 樹)
SQL
CREATE TABLE km_documents (
    document_id VARCHAR(50) PRIMARY KEY,
    file_name VARCHAR(255) NOT NULL,
    total_pages INT NOT NULL,
    json_tree JSONB NOT NULL, -- 儲存預建好的樹狀結構目錄
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
json_tree 的 Schema 規範：

JSON
{
  "toc": [
    {
      "node_id": "N1",
      "heading": "1. 設備開機與環境檢查",
      "start_page": 1,
      "end_page": 5,
      "summary": "開機前的電壓、氣壓與環境溫溼度點檢標準。",
      "children": []
    },
    {
      "node_id": "N2",
      "heading": "2. 生產參數設定",
      "start_page": 6,
      "end_page": 15,
      "summary": "製程參數輸入規範與標準 Taper 曲線。",
      "children": []
    }
  ]
}
表 B：km_document_pages (儲存每一頁的 Raw 內文)
SQL
CREATE TABLE km_document_pages (
    page_id SERIAL PRIMARY KEY,
    document_id VARCHAR(50) REFERENCES km_documents(document_id) ON DELETE CASCADE,
    page_number INT NOT NULL,
    page_content TEXT NOT NULL, -- 該頁原汁原味的 Markdown 內文
    UNIQUE(document_id, page_number)
);
3.3 步驟三：Vector DB 寫入
將文件的「標題 + 整份文件大意摘要」透過 Embedding 模型（如 qwen3-embedding）轉為向量。

存入 Vector DB，並在 Payload 中記錄 document_id, 也需要有版本紀錄。
需有版本管控, 同一份文檔只做一次, 同文檔名但版本不同, 需進行

4. 檢索與推理管線 (Retrieval & Inference Pipeline)
當使用者輸入一個 Query 時，系統的運作架構如下：

4.1 檢索策略選擇 (Strategy Router)
系統總管 Agent (Orchestrator) 接收到 Query 後，進行意圖路由分流：

分支 A (單純向量 RAG)：若使用者提問屬於簡單、一問一答的 FAQ（如「公司的請假流程是什麼？」），直接走傳統向量檢索，撈取 Top-K Chunk 進行回答。

分支 B (混合 Agentic RAG)：若提問涉及複雜技術參數、跨頁步驟、比對（如「機台報警 ERR_01 且真空度不足怎麼辦？」），則啟動 先向量粗篩選 + 後續的PageIndex 樹狀推理流程。

4.2 混合 Agentic RAG 核心實作程式碼
以下為檢索端的完整 Python 實作程式碼，可直接放入專案的 Service 層：

Python
import json
import logging
from typing import List
from openai import OpenAI

# 設置日誌，用於追蹤 Agent 的思考軌跡
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AgenticRAG")

# 初始化地端推論客戶端
LOCAL_LLM_URL = "http://192.168.1.XXX:8000/v1" # 改為公司地端 vLLM/Ollama 的實際 IP
client = OpenAI(base_url=LOCAL_LLM_URL, api_key="local-dummy-key")
MODEL_NAME = "qwen2.5-14b-instruct"

# ========================================================
# 資料庫操作封裝 (DAL - Data Access Layer)
# ========================================================

def db_get_document_tree(doc_id: str) -> dict:
    """從 km_documents 表中撈取預建好的 JSON 樹狀目錄"""
    # 實際開發請改為 SQL 查詢
    # SELECT json_tree FROM km_documents WHERE document_id = :doc_id;
    return {
        "document_id": "doc_txc_001",
        "title": "TXC 製程設備標準作業程序",
        "toc": [
            {"node_id": "N1", "heading": "1. 設備開機與環境檢查", "start_page": 1, "end_page": 5, "summary": "開機前的電壓、氣壓與環境溫溼度點檢標準。"},
            {"node_id": "N2", "heading": "2. 生產參數設定與校正", "start_page": 6, "end_page": 15, "summary": "黃光與蝕刻製程的參數輸入規範與標準 Taper 曲線。"},
            {"node_id": "N3", "heading": "3. 常見異常排除 (Troubleshooting)", "start_page": 16, "end_page": 30, "summary": "針對頻率偏移、真空度不足等四大異常的排查步驟。"}
        ]
    }

def db_get_raw_pages_content(doc_id: str, start_page: int, end_page: int) -> str:
    """從 km_document_pages 表中動態撈取特定頁碼範圍的真實 Raw Markdown 內文"""
    # 實際開發請改為 SQL 查詢
    # SELECT page_content FROM km_document_pages 
    # WHERE document_id = :doc_id AND page_number BETWEEN :start_page AND :end_page 
    # ORDER BY page_number ASC;
    database_mock_rows = {
        16: "### 3.1 真空度不足異常排查\n當設備腔體真空度低於 1.0E-3 Pa 時，可能引發鍍膜不均。請依序確認：\n1. 檢查 O-ring 是否有微小裂痕或粉塵污染。\n2. 檢查分子泵 (Turbo Pump) 轉速是否達到 40,000 RPM。\n3. 若轉速異常，請參考第 17 頁紀錄。",
        17: "### 3.1.2 分子泵驅動器錯誤碼\n- **ERR_01**: 驅動器過熱，請確認冷卻水流量大於 2.0 L/min。\n- **ERR_02**: 電流過載，請立即停機並通知設備工程師。"
    }
    
    selected_raw_text = []
    for page_num in range(start_page, end_page + 1):
        if page_num in database_mock_rows:
            selected_raw_text.append(f"--- [文件 ID: {doc_id} | 第 {page_num} 頁 原始內文] ---\n{database_mock_rows[page_num]}")
            
    return "\n\n".join(selected_raw_text)

# ========================================================
# 核心 Agent 推理與檢索邏輯
# ========================================================

def run_hybrid_agentic_rag(query: str, coarse_matched_doc_ids: List[str]) -> str:
    """
    coarse_matched_doc_ids: 從第一階段 Vector DB 粗篩出來的相關文件 ID 列表
    """
    retrieved_raw_contexts = []
    
    # 遍歷每一份被粗篩出來的文件，各自進行單獨的樹狀巡航 (PageIndex 核心思想)
    for doc_id in coarse_matched_doc_ids:
        doc_tree = db_get_document_tree(doc_id)
        
        # 1. 導航階段 (Navigation Phase)：利用 Summary 進行尋路
        navigation_prompt = f"""
        你現在是 TXC 公司的內部專用 KM 文件導航員。
        同仁目前提出的問題是：'{query}'
        
        以下是《{doc_tree['title']}》這份文件的階層目錄結構與各節點的 Summary 摘要：
        {json.dumps(doc_tree['toc'], ensure_ascii=False, indent=2)}
        
        請進行邏輯推理，判斷哪一個 Node ID 最可能包含回答此問題的精確數據、步驟或細節？
        請嚴格只回傳 JSON 物件，不得包含任何額外贅字，格式規範如下：
        {{"selected_node_id": "NodeID"}}
        """
        
        logger.info(f"正在為文件 {doc_id} 啟動導航 Agent...")
        nav_response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": navigation_prompt}],
            response_format={"type": "json_object"} # 確保地端模型強制輸出 JSON
        )
        
        decision = json.loads(nav_response.choices[0].message.content)
        target_node_id = decision.get("selected_node_id")
        logger.info(f"-> [Agent 推理結果] 判定關鍵章節節點為: {target_node_id}")
        
        # 2. 映射與提取階段 (Mapping & Fetching Phase)：根據節點動態撈取 Raw 內文
        target_node_meta = next((item for item in doc_tree['toc'] if item["node_id"] == target_node_id), None)
        
        if target_node_meta:
            start_p = target_node_meta["start_page"]
            end_p = target_node_meta["end_page"]
            logger.info(f"-> [動態撈取] 正在從關聯式資料庫提取第 {start_p} 頁至第 {end_p} 頁的原始高解析 Markdown...")
            
            # 從資料庫撈取 Raw 內文，而非 Summary
            raw_markdown = db_get_raw_pages_content(doc_id, start_p, end_p)
            retrieved_raw_contexts.append(raw_markdown)
        else:
            logger.warning(f"-> 警告: 導航員給出了不存在的 Node ID: {target_node_id}")

    # 3. 最終合成階段 (Generation Phase)：將 Raw 內文餵給 LLM 生成答案
    if not retrieved_raw_contexts:
        return "地端導航員未能定位到相關的原始文件頁面。"
        
    final_generation_prompt = f"""
    你是一個嚴謹的製造業技術專家，請完全根據以下精確調閱的文件「原始內文（Raw Content）」來回答同仁的問題。
    如果原始內文中沒有提到相關的數據或具體步驟，請誠實回答不知道，絕對不允許捏造任何虛假數據。
    
    【文件參考原始內文】：
    {"\n\n".join(retrieved_raw_contexts)}
    
    【同仁問題】：{query}
    """
    
    logger.info("正在根據原始內文合成最終技術解答...")
    final_response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": final_generation_prompt}]
    )
    
    return final_response.choices[0].message.content

# ========================================================
# 測試入口
# ========================================================
if __name__ == "__main__":
    query_input = "當機台出現真空度不足，且驅動器報 ERR_01 時該怎麼處置？"
    # 模擬階段二：從 Vector DB 粗篩出了這份製程設備 SOP
    vector_db_coarse_results = ["doc_txc_001"] 
    
    print(f"同仁輸入問題: {query_input}\n" + "="*60)
    answer = run_hybrid_agentic_rag(query_input, vector_db_coarse_results)
    print("\n" + "="*25 + " 系統最終輸出結果 " + "="*25 + f"\n{answer}")
5. 開發驗證與優化時程表
階段一：PoC 驗證與環境建置 (預計 1 天)
部署 Docker 版 Qdrant 與 litellm (確保本地 GPU 運作正常)。

安裝 MinerU 並進行測試，確保能將 2-3 份最複雜的公司 SOP 轉為帶頁碼的 Markdown。

階段二：Ingestion 自動化流水線開發 (預計 2 天)
撰寫 Python 腳本，自動將 MinerU 轉換後的 Markdown 結構進行「骨架提取（Regex 抓標題與頁碼）」與「血肉填入（分批呼叫本地 LLM 為各節點生成 Summary）」。

實作 PostgreSQL 兩張核心資料表的寫入邏輯。

階段三：Agent 路由與前端 UI 精緻化 (預計 2 天)
完成「單純向量」與「Agentic RAG」的意圖路由。
文件單一或批次上傳(UI 或者 使用者使用api進行文件上傳)
文件可篩除--> 對應的postgresDB and Qdrant vectorDB也需篩除

前端 UI 優化：利用 Webhook 或 Server-Sent Events (SSE) 動態回傳 Agent 的日誌軌跡，在畫面上呈現「Agent 正在翻閱《TXC設備標準程序》第 16-17 頁...」的視覺效果，建立使用者對 AI 系統的信心。