"""
Warp 响应处理器 - 智能检测和重试机制

实现文档中的解决方案：
1. 智能响应重试机制
2. 事务状态检测
3. 兜底响应机制
"""

import json
import re
import time
from enum import Enum
from typing import Dict, Any, Optional, List
from .logging import logger


class TransactionState(Enum):
    """事务状态枚举"""
    IDLE = "idle"
    ACTIVE = "active"
    FAILED = "failed"
    RETRYING = "retrying"


class WarpResponseHandler:
    """Warp 响应智能处理器"""
    
    def __init__(self, max_retries: int = 2):
        self.transaction_state = TransactionState.IDLE
        self.retry_count = 0
        self.max_retries = max_retries
        self.stuck_indicators = [
            "rollback_transaction",
            "update_task_description",
            r"begin_transaction.*rollback_transaction"
        ]
        self.file_operation_keywords = [
            "创建文件", "修改代码", "写代码", "保存", "文件",
            "create file", "write code", "save", "implement",
            "apply_file_diffs", "create_files", "read_files"
        ]
        
    def handle_sse_event(self, event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理 SSE 事件并检测卡住情况
        
        Args:
            event_data: 解析后的事件数据
            
        Returns:
            处理后的事件数据或重试/兜底响应
        """
        try:
            # 检测事务开始
            if self._contains_action(event_data, "begin_transaction"):
                logger.info("[WarpHandler] 检测到事务开始")
                self.transaction_state = TransactionState.ACTIVE
                self.retry_count = 0
                
            # 检测事务回滚（卡住信号）
            elif self._contains_action(event_data, "rollback_transaction"):
                logger.warning(f"[WarpHandler] 检测到事务回滚，重试次数：{self.retry_count}")
                self.transaction_state = TransactionState.FAILED
                
                if self.retry_count < self.max_retries:
                    self.retry_count += 1
                    self.transaction_state = TransactionState.RETRYING
                    logger.info(f"[WarpHandler] 触发重试机制，第 {self.retry_count} 次重试")
                    return self._create_retry_response()
                else:
                    logger.error("[WarpHandler] 达到最大重试次数，返回兜底响应")
                    return self._create_fallback_response()
                    
            # 检测正常提交
            elif self._contains_action(event_data, "commit_transaction"):
                logger.info("[WarpHandler] 检测到事务提交")
                self.transaction_state = TransactionState.IDLE
                
            # 检测卡住响应特征
            elif self._is_stuck_response(event_data):
                logger.warning("[WarpHandler] 检测到卡住响应特征")
                if self.retry_count < self.max_retries:
                    self.retry_count += 1
                    return self._create_retry_response()
                else:
                    return self._create_fallback_response()
                    
            return self._process_normal_event(event_data)
            
        except Exception as e:
            logger.error(f"[WarpHandler] 事件处理异常：{e}")
            return self._create_error_response(str(e))
    
    def _contains_action(self, event_data: Dict[str, Any], action_type: str) -> bool:
        """检查事件数据是否包含特定的动作类型"""
        try:
            client_actions = event_data.get("client_actions", {})
            if isinstance(client_actions, dict):
                actions = client_actions.get("actions", [])
                if isinstance(actions, list):
                    return any(action_type in action for action in actions)
            return False
        except Exception:
            return False
    
    def _is_stuck_response(self, event_data: Dict[str, Any]) -> bool:
        """检测卡住响应的特征"""
        try:
            event_str = json.dumps(event_data, ensure_ascii=False)
            
            # 检查卡住指示符
            for indicator in self.stuck_indicators:
                if re.search(indicator, event_str, re.IGNORECASE):
                    return True
                    
            # 检查是否只包含任务描述更新而没有实际内容
            if "update_task_description" in event_str:
                # 检查是否同时包含实际的内容输出
                has_content = (
                    "append_to_message_content" in event_str or
                    "agent_output" in event_str or
                    "text" in event_data.get("message", {}).get("agent_output", {})
                )
                if not has_content:
                    logger.warning("[WarpHandler] 检测到只有任务描述更新，无实际内容")
                    return True
                    
            return False
            
        except Exception as e:
            logger.error(f"[WarpHandler] 卡住检测异常：{e}")
            return False
    
    def _create_retry_response(self) -> Dict[str, Any]:
        """创建重试响应"""
        retry_messages = [
            "让我重新为您处理这个请求...",
            "正在尝试不同的方式来帮助您...",
            "切换到更稳定的处理方式..."
        ]
        
        message = retry_messages[(self.retry_count - 1) % len(retry_messages)]
        
        return {
            "choices": [{
                "delta": {
                    "content": f"\n\n🔄 {message}\n\n"
                }
            }]
        }
    
    def _create_fallback_response(self) -> Dict[str, Any]:
        """创建兜底响应"""
        fallback_content = """
⚠️ 由于技术限制，我无法直接执行文件操作。

不过我可以为您提供以下替代方案：

1. **代码示例和指导**：我可以为您提供完整的代码示例和实现思路
2. **分步骤说明**：详细说明如何在您的环境中实现相关功能
3. **最佳实践建议**：分享相关的最佳实践和技术建议

请告诉我您想要实现什么功能，我会为您提供详细的代码示例和实施指导！
        """
        
        return {
            "choices": [{
                "delta": {
                    "content": fallback_content.strip()
                }
            }]
        }
    
    def _create_error_response(self, error_msg: str) -> Dict[str, Any]:
        """创建错误响应"""
        return {
            "choices": [{
                "delta": {
                    "content": f"\n\n❌ 处理过程中出现错误：{error_msg}\n\n请重新尝试您的请求。"
                }
            }]
        }
    
    def _process_normal_event(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理正常事件（透传）"""
        return event_data
    
    def assess_file_operation_risk(self, user_message: str) -> float:
        """评估用户消息触发文件操作的风险"""
        if not user_message:
            return 0.0
            
        risk_patterns = [
            r"创建.*?文件",
            r"写.*?到.*?文件", 
            r"保存.*?代码",
            r"修改.*?\.py|\.js|\.html|\.ts|\.css",
            r"create.*?file",
            r"write.*?to.*?file",
            r"save.*?code",
            r"implement.*?in.*?file"
        ]
        
        risk_score = 0
        for pattern in risk_patterns:
            if re.search(pattern, user_message, re.IGNORECASE):
                risk_score += 1
                
        # 检查关键词
        for keyword in self.file_operation_keywords:
            if keyword.lower() in user_message.lower():
                risk_score += 0.5
                
        return min(risk_score / (len(risk_patterns) + len(self.file_operation_keywords)), 1.0)
    
    def transform_risky_request(self, user_message: str, risk_score: float) -> str:
        """转换高风险请求"""
        if risk_score > 0.7:
            return f"""
请为以下需求提供代码示例和实现建议（以教学方式，不直接创建文件）：

用户需求：{user_message}

请详细解释实现步骤，并提供完整的代码示例。
            """.strip()
        elif risk_score > 0.4:
            return f"""
{user_message}

请注意：我会以代码示例的形式为您提供解决方案。
            """.strip()
            
        return user_message
    
    def get_handler_status(self) -> Dict[str, Any]:
        """获取处理器状态"""
        return {
            "transaction_state": self.transaction_state.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "is_retrying": self.transaction_state == TransactionState.RETRYING
        }


class ContextAwarePromptGenerator:
    """上下文感知的提示词生成器"""
    
    def __init__(self):
        self.file_operation_keywords = [
            "创建文件", "修改代码", "写代码", "保存", "文件",
            "create file", "write code", "save", "implement"
        ]
    
    def generate_system_prompt(self, user_request: str) -> str:
        """根据用户请求动态生成系统提示词"""
        contains_file_ops = any(
            keyword in user_request.lower() 
            for keyword in self.file_operation_keywords
        )
        
        if contains_file_ops:
            return self._generate_no_file_ops_prompt()
        else:
            return self._generate_standard_prompt()
    
    def _generate_no_file_ops_prompt(self) -> str:
        """生成禁用文件操作的提示词"""
        return """
<CRITICAL_CONSTRAINTS>
你是一个代码助手，但你不能创建、修改或操作文件。
你只能：
1. 提供代码建议和示例
2. 解释技术概念
3. 分析现有代码
4. 给出最佳实践建议

当用户要求文件操作时，请明确告知限制并提供替代方案。
</CRITICAL_CONSTRAINTS>
        """.strip()
        
    def _generate_standard_prompt(self) -> str:
        """生成标准提示词"""
        return """
你是一个AI编程助手，可以帮助解答技术问题。
请提供准确、有用的建议。
        """.strip()