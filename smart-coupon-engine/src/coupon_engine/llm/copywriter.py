"""LLM 文案 / 策略解释（plan.md 5.7）。

两个能力：
  - generate_coupon_copy : 惊喜券文案（"🎉 恭喜抽到 XX 元红包！"）
  - explain_strategy     : 给运营看的人话策略解释（方案 6.3 Step3「能在周会上汇报」）

关键约束（plan.md 9.3）：LLM 必须可关闭。没有 API key / LLM_ENABLED=false /
SDK 未安装 / 调用异常时，自动降级为模板文案，保证整条流程永远能跑通。
"""
from __future__ import annotations

from typing import Optional

from ..config import Config, DEFAULT_CONFIG

# .env 加载（可选）
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


class CopyWriter:
    def __init__(self, config: Config = DEFAULT_CONFIG):
        self.config = config
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        if not self.config.llm_enabled:
            return
        try:
            import os

            from anthropic import Anthropic

            kwargs = {}
            if self.config.llm_base_url:
                kwargs["base_url"] = self.config.llm_base_url
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                return  # 没 key 就保持 mock
            self._client = Anthropic(api_key=api_key, **kwargs)
        except Exception:
            self._client = None  # SDK 未装等情况，降级 mock

    @property
    def active(self) -> bool:
        """是否在用真实 LLM（否则为 mock）。"""
        return self._client is not None

    def _complete(self, prompt: str, max_tokens: int = 500) -> Optional[str]:
        if self._client is None:
            return None
        try:
            msg = self._client.messages.create(
                model=self.config.llm_model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        except Exception:
            return None

    # ---- 券文案 ----
    def generate_coupon_copy(self, coupon_value: float, segment_hint: str = "") -> str:
        prompt = (
            f"为电商「惊喜券」抽奖写一句中文文案，用户抽中了 {coupon_value:.0f} 元红包。"
            f"要求：营造惊喜感和运气感，不超过 25 字，可带 1 个 emoji。{segment_hint}"
        )
        out = self._complete(prompt, max_tokens=100)
        if out:
            return out.strip()
        return f"🎉 恭喜！你抽中了 {coupon_value:.0f} 元红包，手气真不错～"

    # ---- 策略解释 ----
    def explain_strategy(self, metrics: dict) -> str:
        prompt = (
            "你是营销数据分析师。基于以下 A/B 实验指标，用中文写一段 3-4 句、"
            "可直接放进周会汇报的结论（讲人话、突出省了多少钱/多赚多少 GMV，"
            "避免 AUC/Qini 等术语）：\n"
            f"{metrics}"
        )
        out = self._complete(prompt, max_tokens=400)
        if out:
            return out.strip()
        return self._mock_explain(metrics)

    @staticmethod
    def _mock_explain(metrics: dict) -> str:
        d = metrics.get("D", {})
        b = metrics.get("B", {})
        inc = d.get("incremental_gmv_total", 0)
        roi = d.get("incremental_roi", 0)
        saving = metrics.get("saving_rate_vs_random", 0)
        return (
            f"智能发券（D 组）相比不发券，带来增量 GMV 约 ¥{inc:,.0f}，"
            f"每投入 1 元券成本拉动 ¥{roi:.2f} 增量销售。"
            f"相比随机发券，券成本节约约 {saving*100:.0f}%，"
            f"说明模型把预算花在了真正会被打动的用户身上，而不是本来就会买的人。"
            f"建议下一轮加大对高 uplift 人群的投放。"
        )
