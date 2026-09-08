from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    glm_api_key: str = ""
    glm_model: str = "glm-5.3-flash"
    glm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    # glm-5.3 系始终思考，档位 low/high 控制思考量
    glm_thinking_effort: str = "high"
    amap_web_key: str = ""
    cors_origins: str = "http://localhost:5173"
    # LangGraph 检查点库；默认禁用（生成任务化后事件缓冲即重连通道，多连接写 sqlite 会锁冲突）
    checkpoint_db: str = ""

    @property
    def has_glm(self) -> bool:
        return bool(self.glm_api_key)

    @property
    def has_amap(self) -> bool:
        return bool(self.amap_web_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
