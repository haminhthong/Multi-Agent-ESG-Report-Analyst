from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cấu hình toàn cục cho ứng dụng Multi-Agent ESG Report Analyst.

    Cung cấp các giá trị mặc định cho đường dẫn cơ sở dữ liệu SQLite và tham số
    truy xuất. Các giá trị này có thể được ghi đè thông qua biến môi trường
    hoặc tệp `.env`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Đường dẫn tệp cơ sở dữ liệu SQLite lưu trữ metadata và chỉ mục full-text FTS5
    database_path: Path = Path("data/esg.db")

    # Số lượng đoạn văn bản (chunks/citations) tối đa được lấy về trong mỗi truy vấn
    top_k: int = 6

    # Giới hạn dung lượng tệp PDF tối đa (75MB)
    max_file_size: int = 75 * 1024 * 1024

    # Cấu hình Local LLM / Ollama / OpenAI-compatible endpoint
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "qwen2.5:7b"
    llm_api_key: str = "ollama"
    llm_timeout: float = 3.0
    use_llm: bool = False

    # Cấu hình Advanced Hybrid Retrieval & Reranker
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    retrieval_mode: str = "hybrid_rerank"  # bm25 | dense | hybrid | hybrid_rerank
    rrf_k: int = 60


# Khởi tạo đối tượng cấu hình singleton sử dụng trong toàn bộ ứng dụng
settings = Settings()
