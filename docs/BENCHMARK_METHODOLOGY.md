# Phương pháp luận Đánh giá & Chuẩn mực Benchmark (Benchmark Methodology)

Tài liệu này công bố minh bạch quy trình xây dựng tập dữ liệu, phương pháp gán nhãn Ground Truth và định nghĩa toán học các chỉ số đo lường phục vụ đánh giá hệ thống **Multi-Agent ESG Report Analyst**.

---

## 1. Quy mô & Cấu trúc Tập Dữ liệu (Dataset Scale & Inventory)

Để loại bỏ hoàn toàn vấn đề "kết quả 1.0 ảo" trên trích đoạn đơn lẻ, hệ thống thiết lập bộ benchmark đa ngành (Cross-Sector Evaluation Suite) bao trùm 3 nhóm ngành trọng điểm:

| Nhóm ngành (Sector) | Doanh nghiệp | Năm báo cáo | Định dạng & Phạm vi | Chủ đề ESG chính |
|---|---|---|---|---|
| **Industrials** | The Boeing Company | 2025 | Báo cáo Phát triển Bền vững | Net-Zero 2030, Scope 1/2/3, An toàn bay & OHS, Đánh giá nhà cung ứng |
| **Energy & Utilities** | NextEra Energy | 2024 | Báo cáo Bền vững & Real Zero | Công suất năng lượng tái tạo (Wind/Solar/Storage), Giảm cường độ phát thải Scope 1, Đa dạng sinh học, Kiểm toán độc lập ERM CVS |
| **Materials & Mining** | Alcoa Corporation | 2024 | Báo cáo Bền vững & Khí hậu | Nhôm phát thải thấp EcoLum, TRIR & Zero Fatality, Bồi hoàn mỏ Bauxite, Đa dạng giới lãnh đạo, Chống tham nhũng |

### Thống kê Định lượng Tổng thể:
- **Số lượng báo cáo đối sánh**: 3 tập tài liệu đa ngành.
- **Số trang trích đoạn chuẩn hóa**: 15 trang trích đoạn đại diện có cấu trúc trang độc lập (`---PAGE X---`).
- **Số lượng truy vấn kiểm thử Retrieval (Retrieval Queries)**: 15 câu hỏi Ground Truth độc lập.
- **Số lượng kiểm thử chất lượng câu trả lời (Answer Eval Cases)**: 10 kịch bản đo lường chuyên sâu.

---

## 2. Quy trình Gán nhãn Chuẩn (Annotation Procedure)

1. **Chuẩn hóa khung tiêu chuẩn**: Các tiêu chí đánh giá được ánh xạ trực tiếp từ các bộ tiêu chuẩn quốc tế:
   - **GRI Standards**: GRI 302 (Năng lượng), GRI 305 (Phát thải khí nhà kính), GRI 403 (An toàn sức khỏe nghề nghiệp), GRI 205 (Chống tham nhũng).
   - **SASB Standards**: Aerospace & Defense, Electric Utilities & Power Generators, Metals & Mining.
   - **TCFD Recommendations**: Quản trị rủi ro khí hậu của Hội đồng quản trị (Board Oversight).
2. **Nguyên tắc Không Rò rỉ Nhãn (Zero Data Leakage)**:
   - Trong quá trình truy xuất, `document_id` và `page` kỳ vọng tuyệt đối **không** được truyền vào câu truy vấn hoặc bộ lọc ngầm.
   - Hệ thống phải tự mở rộng truy vấn và so khớp ngữ nghĩa trên toàn bộ corpus hoặc phạm vi chỉ định (`query_scope`).
3. **Độ phân giải trang (Page-Level Granularity)**:
   - Mỗi câu hỏi được gán nhãn chính xác đến số trang (`document_id`, `page`) chứa dữ liệu trả lời, cho phép kiểm chứng chéo trực tiếp trên tệp PDF gốc.

---

## 3. Định nghĩa Toán học của các Chỉ số Đo lường

### A. Chỉ số Truy xuất Bằng chứng (Retrieval Metrics)

* **Recall@K**: Tỷ lệ các trang chứa bằng chứng kỳ vọng ($E$) được hệ thống tìm thấy trong Top-$K$ kết quả trả về ($R_K$):
  $$\text{Recall@K} = \frac{|R_K \cap E|}{|E|}$$

* **MRR (Mean Reciprocal Rank)**: Nghịch đảo vị trí xuất hiện đầu tiên của trang bằng chứng chuẩn xác ($rank_1$):
  $$\text{MRR} = \frac{1}{|Q|} \sum_{q \in Q} \frac{1}{rank_1(q)}$$

* **Precision@K**: Tỷ lệ các đoạn trích trả về trong Top-$K$ thực sự thuộc tập bằng chứng kỳ vọng:
  $$\text{Precision@K} = \frac{|R_K \cap E|}{K}$$

### B. Chỉ số Chất lượng Câu trả lời & Kiểm soát Ảo giác (Answer Quality & RAG Triad)

* **Citation Correctness**: Tỷ lệ trích dẫn dạng `[Tên tài liệu, trang X]` trong câu trả lời trỏ đúng vào trang tài liệu có thật và đã được truy xuất:
  $$\text{Citation Correctness} = \frac{\text{Số trích dẫn trang hợp lệ}}{\text{Tổng số trích dẫn trong câu trả lời}}$$

* **Answer Faithfulness (Groundedness)**: Tỷ lệ các câu mang khẳng định sự thật (số liệu, tỷ lệ %, năm, cam kết) có bằng chứng trực tiếp hỗ trợ trong văn bản trích đoạn:
  $$\text{Faithfulness} = \frac{\text{Số khẳng định có bằng chứng hỗ trợ}}{\text{Tổng số khẳng định trong câu trả lời}}$$

* **Answer Completeness**: Mức độ bao phủ các ý hỏi và số liệu mục tiêu kỳ vọng từ câu hỏi người dùng:
  $$\text{Completeness} = \frac{\text{Số ý & số liệu kỳ vọng xuất hiện}}{\text{Tổng số yêu cầu kỳ vọng}}$$

* **Unsupported Claim Rate (Hallucination Rate)**: Đo lường trực tiếp tỷ lệ phát ngôn không có căn cứ (nguy cơ bịa đặt thông tin của LLM):
  $$\text{Unsupported Claim Rate} = 1.0 - \text{Faithfulness}$$

---

## 4. Hướng dẫn Tái hiện Kết quả Thực nghiệm (Reproducibility)

```powershell
# 1. Chạy thực nghiệm bóc tách (Ablation Study) 4 cấu hình Retrieval
python -m app.cli benchmark --ablation

# 2. Chạy đánh giá chất lượng câu trả lời và tỷ lệ ảo giác
python -m app.cli evaluate-answer

# 3. Chạy Quality Gate kiểm tra hồi quy trong CI/CD
python -m app.cli evaluate --top-k 5 --min-recall 0.8 --min-mrr 0.8
```
