# Hybride PageIndex RAG

私有化地端「推理式 RAG / 知識庫(KM)」系統。上傳 PDF → MinerU 解析 → PageIndex 章節樹 + 向量化;查詢端是一個 **Agno Agent**,會自主做混合檢索、查 PostgreSQL 取頁原文、判斷可否回答(不行就反問),並以 **ChatGPT 式聊天介面**逐字串流回答、保留會話記憶。回答的每個引用都能點開**證據檢視 modal**,在原始頁面影像上**框出答案實際引用到的文字區塊**。另附 **MinerU 解析測試 Playground** 可互動測試各種解析參數,以及 **RAG 評估分頁**用 golden 題庫量測檢索品質、並可依文件自動產生題庫。

## 技術棧 (Stack)

- 後端:Python 3.12、FastAPI、**Agno**(agent runtime)、OpenAI 相容 LLM(本機 LM Studio)
- 儲存:**PostgreSQL**(文件/頁面/任務/會話)、**Qdrant**(dense + BM25 sparse 混合檢索 + 伺服器端 RRF)
- 解析:**MinerU 3.4**(pipeline / vlm-engine / hybrid-engine;MinerU2.5-Pro VLM)
- 前端:**React 19** + Vite + react-markdown
- 套件管理:uv

## 架構 (Architecture)

```
┌─────────────┐        ┌──────────────────────── FastAPI 後端 (:8200) ───────────────────────┐
│ React 前端  │        │                                                                      │
│  (:5173)    │  /api  │  routes: health / auth / documents / query / chat / mineru / eval   │
│  Vite proxy ├───────▶│                                                                      │
│  ├ 對話聊天 │        │  擷取 (ingestion):                                                   │
│  ├ MinerU   │        │    upload → MinerU 解析 → 頁碼標記 Markdown → PageIndex 章節樹        │
│  │  測試頁  │        │    → 每節點 summary 向量 + BM25 sparse 寫入 Qdrant、頁面寫入 PG       │
│  └ 評估     │        │                                                                      │
└─────────────┘        │                                                                      │
                       │  查詢 (Agno Agent):                                                  │
                       │    search_knowledge(Qdrant 混合檢索) → PostgresTools 取頁原文        │
                       │    → 可答性自評 → 逐字串流答案 + 思考過程 + 會話記憶(PostgresDb)    │
                       └──────────┬───────────────┬──────────────┬───────────────┬───────────┘
                                  │               │              │               │
                            ┌─────▼────┐   ┌──────▼─────┐  ┌─────▼──────┐  ┌─────▼────────┐
                            │PostgreSQL│   │   Qdrant   │  │ LM Studio  │  │ mineru-api   │
                            │ (:5433)  │   │  (:6333)   │  │ LLM+Embed  │  │ sidecar:8201 │
                            └──────────┘   └────────────┘  └────────────┘  └──────────────┘
```

- **PageIndex**:把文件拆成章節節點(含頁碼範圍),每個節點的摘要做向量 + 稀疏索引;查詢先命中節點,再依其頁碼範圍取原文。
- **Agent 自主檢索**:`search_knowledge` 工具包現有 Qdrant 混合檢索;`PostgresTools` 用固定 SQL 依 `document_id` + 頁碼範圍取 `km_document_pages` 原文;答不出來時回 `need_clarification` / `insufficient`。
- **會話記憶**:Agno `PostgresDb`(`add_history_to_context`,保留前 5 輪),存於專屬表 `hybride_chat_sessions`。
- **MinerU Playground**:後端代理 MinerU 自帶的 `mineru-api`(常駐 sidecar,埠 8201),可測 pipeline / vlm / hybrid 等參數。
- **引用證據框選**:對話回答的每個引用可點開「證據」modal,後端用 `pypdfium2` 把引用頁渲成 PNG(快取),從 MinerU `middle.json` 取該頁文字區塊 bbox(以 `page_size` 正規化成 0~1),並用大小寫無關的字元 bigram 比對,把**答案實際引用到的區塊**框成琥珀色、其餘區塊淡框;支援引用頁範圍翻頁。全部即時讀磁碟上既有產物,不需重新擷取或改資料庫。
- **RAG 評估(評估分頁)**:用 golden 題庫量測 `page_hit` / `doc_hit` / `MRR` / `answered` 等指標,並可切換 `strategy` / `reranker` / `node_hits` 做 A/B;也能**依選定文件用 LLM 自動產生 golden 題庫**(每頁出題、答案來源即該頁)。

## 啟動 (Run)

> 連接埠:**後端 8200**、**前端 5173**、**MinerU sidecar 8201**(自動啟動)。
> 本機把後端跑在 8200(預設 8000 被其他服務佔用);前端 Vite proxy 已指向 8200(可用 `VITE_API_TARGET` 覆寫)。

**前置服務**(`.env` 開啟 `USE_DATABASE` / `USE_QDRANT` / `USE_AGNO` 時需要):PostgreSQL(`127.0.0.1:5433`)、Qdrant(`:6333`)、OpenAI 相容 LLM + Embedding(本機 LM Studio)。

**1. 安裝 + 設定**

```powershell
uv sync
Copy-Item .env.example .env   # 再依需求編輯 .env
```

Python 鎖定 `>=3.12,<3.13`(MinerU 在 Windows 不支援 3.13)。

**2. 後端**(埠 8200)

```powershell
uv run uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8200 --reload
# 健康檢查
Invoke-RestMethod http://127.0.0.1:8200/api/health
```

**3. 前端**(埠 5173)

```powershell
cd frontend
npm.cmd install
npm.cmd run dev -- --host 127.0.0.1 --port 5173
```

開啟 `http://127.0.0.1:5173`(對話 + MinerU 測試)。

**4.(選用)資料庫 / 向量庫初始化**

```powershell
uv run python scripts/bootstrap_db.py
uv run python scripts/bootstrap_qdrant.py
```

**5.(選用)啟用 MinerU vlm / hybrid 後端** — 下載 MinerU2.5-Pro 模型一次即可:

```powershell
uv run mineru-models-download -m vlm -s modelscope
```

**測試 / 建置驗證:**

```powershell
uv run pytest
uv run ruff check backend scripts
cd frontend
npm.cmd run test
npm.cmd run build
```

Live end-to-end verification with PostgreSQL and Qdrant:

```powershell
$env:USE_DATABASE="true"
$env:USE_QDRANT="true"
$env:DB_PASSWORD="your-db-password"
uv run python scripts/bootstrap_db.py
uv run python scripts/bootstrap_qdrant.py
uv run python scripts/e2e_live.py
```

Live end-to-end verification with the real MinerU CLI:

```powershell
$env:USE_DATABASE="true"
$env:USE_QDRANT="true"
$env:DB_PASSWORD="your-db-password"
$env:MINERU_BACKEND="pipeline"
uv run python scripts/e2e_mineru_live.py
```

## API 一覽 (API Reference)

所有路由前綴 `/api`。啟用 `REQUIRE_AUTH=true` 時,除 `health` / `auth/login` 外都需帶 `Authorization: Bearer <token>`。

### 健康檢查
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/health` | 服務狀態(`status` / `app_name` / `environment`)。 |

### 認證 `auth`
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/auth/login` | 帳密登入,回傳 bearer token(body:`username` / `password`)。 |
| GET | `/api/auth/me` | 取得目前登入者(username / role)。 |

### 文件 `documents`
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/documents` | 上傳 PDF(multipart `file`)。回傳 `job_id` / `document_id`;同內容去重、同檔名新內容自動升版。 |
| GET | `/api/documents?latest_only=` | 文件清單(`latest_only=true` 只列最新版)。 |
| GET | `/api/documents/{id}` | 單一文件詳情(含 PageIndex 章節樹 `toc`)。 |
| GET | `/api/documents/{id}/pages` | 逐頁原文。 |
| GET | `/api/documents/{id}/pages/{page}/image` | 該頁渲染成 PNG(`pypdfium2`,結果快取),供證據框選的底圖。 |
| POST | `/api/documents/{id}/pages/{page}/evidence` | 該頁文字區塊(MinerU `middle.json` 的 `para_blocks`,bbox 正規化 0~1)+ 以 body 的 `answer` / `query` 比對標記 `matched` 的答案來源區塊。無 MinerU 區塊資料時回 `has_regions=false`。 |
| GET | `/api/documents/{id}/versions` | 同檔名的所有版本。 |
| GET | `/api/documents/jobs/{job_id}` | 擷取任務狀態(queued / processing / completed / failed)。前端輪詢此端點顯示進度。 |
| POST | `/api/documents/jobs/{job_id}/process` | 同步觸發擷取(背景 worker 開啟時不需手動呼叫)。 |
| DELETE | `/api/documents/{id}` | 刪除文件 + 清 PostgreSQL / Qdrant 向量 / 來源檔(含日期路徑)。 |

### 查詢 `query`(Agno Agent)
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/query` | 一次性問答。body:`query`(必填)、`mode`、`top_k`、`strategy`(覆寫檢索策略)、`session_id`。回傳 `answer` / `status`(answered / need_clarification / insufficient)/ `clarifying_question` / `citations` / `trace`。 |
| POST | `/api/query/stream` | **SSE 串流**(聊天介面用)。事件:`event: token`(逐字答案)、`event: reasoning`(模型推理)、`event: trace`(階段/工具調用)、`event: final`(最終 `QueryResponse`)。 |

### 對話歷史 `chat`
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/chat/sessions` | 歷史會話清單(`session_id` / `title`=首句 / `updated_at`)。 |
| GET | `/api/chat/sessions/{id}/messages` | 重載某會話的完整 user/assistant 訊息。 |
| DELETE | `/api/chat/sessions/{id}` | 刪除某會話。 |

### 評估 `eval`(檢索品質 / Golden 題庫)
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/eval/golden` | 目前 golden 題庫(`query` / `file_name` / `page_number` / `expected_answer`)。 |
| POST | `/api/eval/run` | 用 golden set 跑檢索(預設不做 LLM 合成,快約 30×)並回指標:`doc_hit_rate` / `page_hit_rate` / `mrr` / `answered_rate` / 延遲。可帶 `strategy` / `rerank_provider` / `cohere_model` / `node_hits` / `top_k` / `limit` 暫時覆寫設定做 A/B。 |
| POST | `/api/eval/generate` | 依選定文件用 LLM 產生 golden 題目(body:`doc_ids`(空=全部已完成文件)/ `per_doc` / `questions_per_page` / `min_chars` / `append`)。依 id 去重;回 `added` / `total` 與新增題目。 |

### MinerU 解析測試 `mineru`
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/mineru/status` | sidecar 狀態(`base_url` / `managed` / `healthy`)。 |
| POST | `/api/mineru/parse` | 解析測試(multipart `file` + 參數:`backend` / `parse_method` / `lang` / `formula_enable` / `table_enable` / `image_analysis` / `effort` / `start_page_id` / `end_page_id` / `server_url`)。回傳 `markdown` / `content_list` / `images`(base64)/ `backend` / `version` / `elapsed_ms`。 |

## MinerU 文件解析

本專案以 **MinerU 3.4.0**(`mineru[core]>=3.4.0`)把上傳的 PDF 轉成結構化內容,再餵給 PageIndex 建立章節樹與向量。

### 安裝與流程

- 安裝路徑用官方 `mineru[core]`(`mineru[all]` 在 Windows 會解析成 Linux-only 的 GPU 套件,故不採用)。
- 擷取時先找既有產物;沒有才呼叫 `MINERU_COMMAND`(以 `MINERU_BACKEND` / `MINERU_METHOD` / `MINERU_FORMULA` / `MINERU_TABLE` 參數執行)。
- **儲存路徑依日期分區**,方便依日期尋找:上傳原檔 `uploads/source/YYYY-MM-DD/{document_id}/`、MinerU 產物 `uploads/mineru/YYYY-MM-DD/{document_id}/`、Playground 解析輸出 `output/mineru-api/YYYY-MM-DD/`。(日期取文件建立時間;讀取時相容舊的非日期 `uploads/mineru/{document_id}` 路徑。)
- MinerU 產生 `*_content_list.json`(結構化版面清單);本專案**優先讀這個檔**,依 `page_idx` 重建「帶頁碼標記」的 Markdown 給 PageIndex(`<!-- page: N -->`),`text_level` 轉成 Markdown 標題層級(`#`~`######`)。
- 若 MinerU 未安裝或無可用輸出,退回本機 `pypdf` 逐頁抽文字,並在任務訊息中註記。

### 兩種後端(`MINERU_BACKEND`)

- **`pipeline`(本專案預設)**:模組化傳統 CV 流程——版面分析 + PP-OCRv5 OCR(約 37 種語言)+ 表格辨識模型 + 公式辨識模型 + 閱讀順序排序。GPU 需求低(約 8GB 可跑),在本機 RTX 5090 上約 8 頁 / 31 秒。
- **`vlm`(MinerU2.5)**:約 1.2B 參數的視覺語言模型,單模型端到端解析,複雜版面 / 手寫 / 跨欄精度更高(官方稱可超越 10B~100B 級模型);可搭 `vllm` / `lmdeploy`(Windows 原生加速)/ Apple `mlx` 後端。資源需求較高,適合對精度要求高的場景。

### 表格與圖片處理

MinerU 本身在表格與圖片上相當強,且近版持續加強:

- **表格**:有線 / 無線(borderless)/ 半結構表格、旋轉 0/90/270 度、**跨頁表格自動合併**、**表格內的公式與圖片**、印章 / 直書文字辨識;表格以 **HTML 結構**輸出於 `content_list.json` 的 `table_body` 欄位,並附 bbox 位置。
- **圖片 / 圖表**:擷取圖片檔(`img_path`)並與 **caption / footnote 自動配對**(近版修正了多圖多表的配對準確度)。
- **公式**:數學式辨識輸出 LaTeX,長公式與中英混合公式準確度近版大幅提升。

> ✅ **本專案如何納入表格 / 圖片**:`backend/app/services/mineru.py` 的 `_markdown_from_content_list` 除了內文與標題,也會把 **表格**(`table_body` 的 HTML 攤平成 `儲存格 | 儲存格` 純文字、含 caption / 附註)與 **圖片的 caption / footnote** 併入該頁 Markdown。如此一來表格與圖說會進入頁面內文,被章節摘要、向量與 BM25、以及 Agent 取頁原文所使用,提升含表格 / 圖表文件的檢索與問答品質。(圖片本身為二進位,僅納入其文字說明。)

### MinerU 最新版本動態(2026）

- VLM 後端已升級至 **MinerU2.5**(`vlm` backend 2.5),新增 `vlm-lmdeploy-engine`(Windows 原生推理加速)與 `vlm-mlx-engine`(Apple Silicon,較 transformers 後端快 100%~200%)。
- 表格採「混合表格結構解析」演算法 + 有線表格模型;OCR 速度與多語準確度近版顯著提升;全面支援 PDF / 圖片 / DOCX / PPTX / XLSX。
- 來源:[MinerU GitHub](https://github.com/opendatalab/MinerU)、[MinerU Changelog](https://opendatalab.github.io/MinerU/reference/changelog/)、[MinerU2.5 論文](https://arxiv.org/html/2509.22186v2)。

### MinerU 解析測試 Playground

前端側欄的「**MinerU 測試**」分頁可上傳 PDF、調整各種參數(backend / method / 語言 / 公式 / 表格 / 影像分析 / 頁碼範圍)即時看解析結果(Markdown / content_list / 圖片)。

- 後端以 **MinerU 內建 FastAPI(`mineru-api`)** 為引擎:首次使用時自動在 **127.0.0.1:8201**(避開被佔用的 8000)啟動一個常駐 sidecar,模型常駐記憶體 → 反覆改參數重跑較快。相關設定:`MINERU_API_PORT`(預設 8201)、`MINERU_API_AUTOSTART`(預設 true)、`MINERU_API_URL`(指定外部 mineru-api 則不自動啟動)。
- API:`POST /api/mineru/parse`(multipart:檔案 + 參數)、`GET /api/mineru/status`。

#### 啟用 vlm / hybrid 後端

`pipeline` 後端開箱即用。要使用 `vlm-engine` / `hybrid-engine`(MinerU2.5 視覺語言模型)需先下載模型:

```powershell
uv run mineru-models-download -m vlm -s modelscope   # 或 -s huggingface / auto
```

`mineru[core]` 已內含 `vlm` extra(`transformers` + `accelerate`),下載模型後即可透過 transformers 推理(在 GPU 上可跑、速度中等)。若要更快可選裝加速引擎 `uv add "mineru[lmdeploy]"`(Windows 原生加速;若該 CUDA / GPU 架構無對應 wheel 會安裝失敗,屆時仍可用 transformers)。

Query streaming:

```powershell
Invoke-RestMethod http://127.0.0.1:8200/api/query -Method Post -ContentType "application/json" -Body '{"query":"ERR_01 真空度不足要怎麼處理？","mode":"auto","top_k":5}'
```

The frontend uses `POST /api/query/stream` to render live Agent trace events and then the final answer.

Retrieval strategy can be set globally (`RETRIEVAL_STRATEGY=dense|bm25|hybrid`) or per request:

```powershell
Invoke-RestMethod http://127.0.0.1:8200/api/query -Method Post -ContentType "application/json" -Body '{"query":"真空度不足","mode":"auto","top_k":5,"strategy":"bm25"}'
```

## 對話引用證據(頁面框選)

在「對話」分頁,點任一回答下方的引用 chip 會開啟**證據檢視 modal**:在引用頁的原始 PDF 影像上,框出**答案實際引用到的文字區塊**。

- **資料來源**:區塊座標來自 MinerU 的 `*_middle.json`(`pdf_info[].para_blocks` 的 `bbox`,與 `page_size` 同座標空間;content_list 的 bbox 是另一個縮放空間,不採用)。bbox 以 `page_size` 正規化成 0~1 比例,前端再依影像實際尺寸用百分比疊框,與渲染倍率無關。
- **頁面影像**:後端用 `pypdfium2`(MinerU 既有相依,免裝新套件)把原始上傳 PDF 的該頁渲成 PNG,快取於 `uploads/render/{doc}/`。
- **比對哪些區塊**:`POST …/evidence` 收 `answer` / `query`,用**大小寫無關的字元 bigram overlap** 為每個區塊評分,超過門檻者標 `matched`(命中為琥珀色框,其餘為淡灰框);若無區塊跨過門檻,仍保底標記最相關的一塊,modal 不會空白。
- **優雅退回**:示範文件或以 `pypdf` fallback 擷取、沒有 `middle.json` 的文件,`evidence` 回 `has_regions=false`,modal 僅顯示頁面影像(或在無原始 PDF 時提示無法產生影像)。
- 全部即時讀磁碟上既有的 MinerU 產物與原始 PDF,**不需重新擷取、不改資料庫**,既有文件即時可用。modal 內可在引用頁範圍翻頁,並以「檢視全文」開啟既有的文件章節 / 逐頁瀏覽器。

## RAG 評估(評估分頁)

「評估」分頁用一組 **golden 題庫**(`backend/eval/golden_set.jsonl`,每題標註正解文件與頁碼)量測檢索品質,並支援依文件自動產生題庫。

- **執行評估**(`POST /api/eval/run`):把 golden set 跑過檢索 pipeline,回 `page_hit_rate` / `doc_hit_rate` / `MRR` / `answered_rate` / 延遲等指標。預設**只跑檢索不做 LLM 合成**(約 30× 快),適合掃描調參。前端可切換 `strategy`(dense / hybrid / bm25)、`reranker`(bm25 / cohere)、`node_hits`、`top_k`、題數,於單次執行內暫時覆寫全域設定做 A/B(執行中設定為行程全域,單人評估工具可接受)。
- **製作 Golden 題庫**(`POST /api/eval/generate`):勾選已完成文件、設定每文件取樣頁數 / 每頁題數 / 最小字數 / 是否附加,後端對取樣頁用 LLM 出題(該頁即為正解來源),依 id 去重後寫入 golden set 並刷新題庫表。建議事後人工校正。
- 也可用命令列:`PYTHONPATH=backend uv run python -m eval.run_eval --label baseline` 與 `python -m eval.generate_golden --per-doc 3`,並以 `eval.compare` 比較不同 run。

## 環境設定（`.env`）說明

以下為 `.env` 各項開關（`true`/`false`）與關鍵設定的用途。預設值多為「最簡可跑」，正式使用時依需求開啟。

### 核心開關

| 設定 | 預設 | 用途 |
|------|------|------|
| `USE_DATABASE` | `false` | `true` 時文件 / 頁面 / 任務狀態存入 **PostgreSQL**；`false` 用程序內記憶體(僅 PoC，重啟即失)。正式使用請開 `true`。 |
| `USE_QDRANT` | `false` | `true` 時節點向量寫入 / 查詢 **Qdrant**(dense + BM25 sparse 混合檢索)；`false` 退回程序內 BM25。要用語義 / 混合檢索請開 `true`。 |
| `USE_BACKGROUND_WORKER` | `false` | `true` 時上傳後在**背景執行緒佇列**解析,上傳立即回應、不阻塞;`false` 需手動呼叫 `/process` 端點。 |
| `USE_AGNO` | `false` | `true` 時查詢走 **Agno Agent**(自主混合檢索 + PostgresTools 取頁原文 + 可答性自評 + 逐字串流 + 會話記憶);`false` 退回決定式檢索 pipeline。本系統的對話介面需 `true`。 |
| `REQUIRE_AUTH` | `false` | `true` 時 API 需 bearer token。帳號設於 `AUTH_USERS`(`帳號:密碼:角色`,角色 `admin` 可看全部文件),以 `POST /api/auth/login` 登入。 |
| `LLM_TOC_SUMMARY` | `false` | `true` 時對**每個 TOC 章節節點以 LLM 產生摘要**(較慢,一節點一次 LLM 呼叫);`false` 用快速的抽取式摘要。此摘要會被拿去做向量與 BM25,**直接影響檢索品質**(詳見下節)。 |

### 文件解析(MinerU)

| 設定 | 預設 | 用途 |
|------|------|------|
| `MINERU_COMMAND` | `mineru` | MinerU CLI 指令名稱 / 路徑。 |
| `MINERU_BACKEND` | `pipeline` | 解析後端:`pipeline`(模組式 CV+OCR,GPU 8GB 即可)或 `vlm`(MinerU2.5 視覺語言模型,精度更高、吃更多資源)。詳見「MinerU 文件解析」。 |
| `MINERU_METHOD` | `auto` | `auto` / `txt`(純數位 PDF 跳過 OCR,快)/ `ocr`(強制 OCR,適合掃描檔)。 |
| `MINERU_FORMULA` | `true` | 是否啟用**公式辨識模型**(數學式 → LaTeX)。CPU 環境可關以加速。 |
| `MINERU_TABLE` | `true` | 是否啟用**表格辨識模型**(輸出表格結構 / HTML)。CPU 環境可關以加速。 |
| `MINERU_TIMEOUT_SECONDS` | `1200` | 單檔解析逾時(秒)。 |

### 檢索

| 設定 | 預設 | 用途 |
|------|------|------|
| `RETRIEVAL_STRATEGY` | `hybrid` | 全域檢索策略:`dense`(向量)/ `bm25`(關鍵字)/ `hybrid`(兩者 + 伺服器端 RRF 融合)。可於單次請求以 `strategy` 覆寫。 |
| `RETRIEVAL_RERANK` | `true` | `true` 時對候選頁面再做一次 BM25 重排。 |
| `BM25_K1` / `BM25_B` | `1.5` / `0.75` | 程序內 BM25 fallback 的調參。 |

### LLM / Embedding / 其他

- `LITELLM_BASE_URL` / `LITELLM_API_KEY` / `MODEL_ID` — 對話 / 摘要用的 OpenAI 相容 LLM(本機指向 LM Studio)。
- `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` / `EMBEDDING_CONTEXT_LENGTH` / `EMBEDDING_TIMEOUT_SECONDS` — 向量模型(1024 維,須與 `QDRANT_VECTOR_SIZE` 一致)。
- `SYNTHESIS_MAX_TOKENS` / `SYNTHESIS_TIMEOUT_SECONDS` — 合成回答的輸出長度與逾時(qwen 為 reasoning model,需足夠 token)。
- `QDRANT_URL` / `QDRANT_COLLECTION` / `QDRANT_VECTOR_SIZE`、`DB_*` — Qdrant 與 PostgreSQL 連線。
- `PHOENIX_ENDPOINT` / `PHOENIX_PROJECT` / `PHOENIX_PROTOCOL` — OpenTelemetry 追蹤匯出至 Phoenix(設定即啟用,需 `uv sync --extra observability`)。

### TOC 摘要與檢索品質的關係

擷取流程會把每個 PageIndex 章節節點的 **summary 文字拿去產生 dense 向量與 BM25 sparse 向量**(見 `backend/app/services/vector_store.py`),所以**摘要文字就是被檢索的內容**。

- `LLM_TOC_SUMMARY=false`(目前狀態):用抽取式摘要(標題 + 章節前兩句),速度快、擷取不需 LLM。
- `LLM_TOC_SUMMARY=true`:用 LLM 產生更精煉、語義更完整的摘要。通常能**提升 dense 語義召回**(摘要更貼近使用者的自然語言提問);對 BM25 則不一定(LLM 可能改寫掉原文關鍵詞)。代價是擷取變慢(每節點一次 LLM 呼叫)。

建議:文件量不大、追求檢索品質時開 `true`;大量批次擷取、追求速度時維持 `false`。改動後需**重新擷取**文件才會套用到向量。

## Observability (Phoenix)

OpenTelemetry trace export is enabled when `PHOENIX_ENDPOINT` is set. Install the exporters and the
Phoenix viewer with the optional extra:

```powershell
uv sync --extra observability
```

Run Phoenix locally (default OTLP endpoint `http://127.0.0.1:6006/v1/traces`), set
`PHOENIX_ENDPOINT`, and the retrieval pipeline spans plus Agno LLM spans will appear in Phoenix.

## Documents

- [System Survey](docs/system-survey.md)
- [Architecture](docs/architecture.md)
- [Implementation Plan](docs/implementation-plan.md)
- [API Contract](docs/api-contract.md)
- [Security Notes](docs/security-notes.md)
- [Remaining Work](docs/remaining-work.md)
