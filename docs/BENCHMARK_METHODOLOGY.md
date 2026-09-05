# Phương pháp luận Đánh giá & Chuẩn mực Benchmark (Benchmark Methodology)
## Evidence-Grounded ESG Intelligence & Audit System

Tài liệu này công bố minh bạch quy trình xây dựng tập dữ liệu kiểm chuẩn, phương pháp gán nhãn Ground Truth và định nghĩa toán học các chỉ số đo lường 4 tầng (4-Tier Evaluation) phục vụ đánh giá hệ thống.

---

## 1. Quy mô & Cấu trúc Tập Dữ liệu Đa ngành (Cross-Sector Evaluation Suite)

Để đảm bảo tính khách quan và loại bỏ hoàn toàn vấn đề "kết quả 1.0 ảo" trên trích đoạn đơn lẻ, hệ thống thiết lập bộ benchmark đa ngành bao trùm 3 nhóm ngành trọng điểm:

| Nhóm ngành (Sector) | Doanh nghiệp | Năm báo cáo | Định dạng & Phạm vi | Chủ đề ESG chính & Hard Negatives |
|---|---|---|---|---|
| **Industrials & Aerospace** | The Boeing Company | 2023 - 2025 | Báo cáo Phát triển Bền vững | Net-Zero 2030, Scope 1/2/3, An toàn bay & OHS, Đánh giá nhà cung ứng, **Hard Negative: Tuyên bố báo cáo không được kiểm toán (Trang 70)** |
| **Energy & Utilities** | NextEra Energy | 2024 | Báo cáo Bền vững & Real Zero | Công suất năng lượng tái tạo (Wind/Solar/Storage), Giảm cường độ phát thải Scope 1, Đa dạng sinh học, Kiểm toán độc lập ERM CVS |
| **Materials & Mining** | Alcoa Corporation | 2024 | Báo cáo Bền vững & Khí hậu | Nhôm phát thải thấp EcoLum, TRIR & Zero Fatality, Bồi hoàn mỏ Bauxite, Đa dạng giới lãnh đạo, Chống tham nhũng |

### Thống kê Định lượng Tổng thể:
- **Số lượng báo cáo đối sánh**: 3 tập tài liệu đa ngành.
- **Số trang trích đoạn chuẩn hóa**: 16 trang trích đoạn đại diện có cấu trúc trang độc lập (`---PAGE X---`), bao gồm cả bảng số liệu và phản ví dụ (hard negatives).
- **Số lượng truy vấn kiểm chuẩn Retrieval**: 21 câu hỏi Ground Truth độc lập (tăng từ 15 cases ban đầu, bổ sung các câu hỏi về bảng, mâu thuẫn số liệu và so sánh).
- **Số lượng ca kiểm chuẩn trích xuất số liệu (Extraction Cases)**: 10 ca kiểm thử cấu trúc số liệu định lượng (Scope 1/2/3, Targets, Baseline, TRIR).
- **Số lượng ca kiểm chuẩn chất lượng câu trả lời (Answer Eval Cases)**: 10 kịch bản đo lường chuyên sâu.

---

## 2. Khung Đánh giá Toàn diện 4 Tầng (4-Tier Evaluation Architecture)

```
┌────────────────────────────────────────────────────────────────────────┐
│               Tier 1: Retrieval & Reranking Performance                │
│       Hit@K · Recall@K · MRR@K · nDCG@K · Page Boundary Accuracy       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               Tier 2: Structured ESG Fact Extraction                   │
│        Precision · Recall · F1-Score · Unit Normalization Rate         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│             Tier 3: Answer Faithfulness & Groundedness                 │
│      Citation Correctness · Claim Faithfulness · Hallucination Rate     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│         Tier 4: ESG Rubric Coverage & Greenwashing Screening           │
│    Disclosure Coverage % · Target Credibility · Evidence Quality       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Định nghĩa Toán học của các Chỉ số Đo lường

### A. Tầng 1: Chỉ số Truy xuất Bằng chứng (Retrieval Metrics)

* **Recall@K / Hit@K**: Tỷ lệ các trang chứa bằng chứng kỳ vọng ($E$) được hệ thống tìm thấy trong Top-$K$ kết quả trả về ($R_K$):
  $$\text{Recall@K} = \frac{|R_K \cap E|}{|E|}$$

* **MRR (Mean Reciprocal Rank)**: Nghịch đảo vị trí xuất hiện đầu tiên của trang bằng chứng chuẩn xác ($rank_1$):
  $$\text{MRR} = \frac{1}{|Q|} \sum_{q \in Q} \frac{1}{rank_1(q)}$$

* **nDCG@K (Normalized Discounted Cumulative Gain)**: Đánh giá chất lượng xếp hạng có trọng số vị trí, ưu tiên đưa bằng chứng quan trọng nhất lên đầu:
  $$\text{DCG}@K = \sum_{i=1}^K \frac{2^{rel_i} - 1}{\log_2(i + 1)}, \quad \text{nDCG}@K = \frac{\text{DCG}@K}{\text{IDCG}@K}$$
  *(Trong đó $rel_i = 1$ nếu chunk thứ $i$ trúng đúng trang ground truth, ngược lại $rel_i = 0$).*

### B. Tầng 2: Chỉ số Bóc tách Số liệu Có cấu trúc (Extraction Metrics)

Đối với mỗi chỉ tiêu ESG (Scope 1, Scope 2, Scope 3, Net-Zero Year, Baseline Year, TRIR):
* **Precision**: Tỷ lệ các số liệu trích xuất thực sự trùng khớp với ground truth về giá trị và đơn vị.
* **Recall**: Tỷ lệ các số liệu có mặt trong văn bản được trích xuất thành công.
* **F1-Score**: Trung bình điều hòa giữa Precision và Recall:
  $$F_1 = 2 \cdot \frac{\text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$

### C. Tầng 3: Chất lượng Câu trả lời & Kiểm soát Ảo giác (Answer Quality & RAG Triad)

* **Citation Correctness**: Tỷ lệ trích dẫn dạng `[Tên tài liệu, trang X]` trong câu trả lời trỏ đúng vào trang tài liệu có thật và đã được lập chỉ mục:
  $$\text{Citation Correctness} = \frac{\text{Số trích dẫn trang hợp lệ}}{\text{Tổng số trích dẫn trong câu trả lời}}$$

* **Answer Faithfulness (Groundedness)**: Tỷ lệ các câu mang khẳng định sự thật (số liệu, tỷ lệ %, năm, cam kết) có bằng chứng trực tiếp hỗ trợ trong văn bản trích đoạn:
  $$\text{Faithfulness} = \frac{\text{Số khẳng định có bằng chứng hỗ trợ}}{\text{Tổng số khẳng định trong câu trả lời}}$$

* **Unsupported Claim Rate (Hallucination Rate)**: Đo lường trực tiếp tỷ lệ phát ngôn không có căn cứ (nguy cơ bịa đặt thông tin):
  $$\text{Unsupported Claim Rate} = 1.0 - \text{Faithfulness}$$

### D. Tầng 4: Độ phủ Chuẩn mực & Sàng lọc Greenwashing

* **Disclosure Coverage %**: Tỷ lệ tiêu chí GRI/SASB được công bố có bằng chứng xác thực trong tổng số tiêu chí chuẩn mực kiểm toán.
* **Greenwashing Risk Level**: Tổng hợp điểm cảnh báo đa tín hiệu theo ngưỡng:
  - `LOW`: $0 - 1$ điểm cảnh báo (Đầy đủ số liệu, có năm cơ sở, có kiểm toán độc lập).
  - `MEDIUM`: $2 - 4$ điểm cảnh báo (Thiếu năm cơ sở hoặc thiếu bảo đảm độc lập).
  - `HIGH`: $\ge 5$ điểm cảnh báo (Lạm dụng từ ngữ tham vọng, hoàn toàn thiếu số liệu định lượng, phát thải tăng).

---

## 4. Hướng dẫn Tái hiện Kết quả Thực nghiệm (Reproducibility Commands)

```powershell
# 1. Chạy thực nghiệm bóc tách Ablation Study trên 4 cấu hình Retrieval (21 test cases)
python -m app.cli benchmark --top-k 5

# 2. Chạy đánh giá độ chính xác trích xuất số liệu có cấu trúc (Tier 2 Extraction)
python -m app.cli evaluate-extraction

# 3. Chạy đánh giá chất lượng câu trả lời, độ trung thực và tỷ lệ ảo giác (RAG Triad)
python -m app.cli evaluate-answer --top-k 5

# 4. Chạy Quality Gate kiểm tra hồi quy trong CI/CD pipeline
python -m app.cli evaluate --top-k 5 --min-recall 0.8 --min-mrr 0.8

# 5. Chạy toàn bộ 43 bài kiểm thử tự động
python -m pytest
```
