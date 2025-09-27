#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Warp API客户端模块

处理与Warp API的通信，包括protobuf数据发送和SSE响应解析。
"""
import httpx
import os
import base64
import binascii
from typing import Optional, Any, Dict
from urllib.parse import urlparse
import socket

from ..core.logging import logger
from ..core.protobuf_utils import protobuf_to_dict
from ..core.auth import get_valid_jwt, check_and_refresh_token, mark_current_account_quota_exhausted
from ..config.settings import WARP_URL as CONFIG_WARP_URL


def _get(d: Dict[str, Any], *names: str) -> Any:
    """Return the first matching key value (camelCase/snake_case tolerant)."""
    for name in names:
        if name in d:
            return d[name]
    return None


def _get_event_type(event_data: dict) -> str:
    """Determine the type of SSE event for logging"""
    if "init" in event_data:
        return "INITIALIZATION"
    client_actions = _get(event_data, "client_actions", "clientActions")
    if isinstance(client_actions, dict):
        actions = _get(client_actions, "actions", "Actions") or []
        if not actions:
            return "CLIENT_ACTIONS_EMPTY"
        
        action_types = []
        for action in actions:
            if _get(action, "create_task", "createTask") is not None:
                action_types.append("CREATE_TASK")
            elif _get(action, "append_to_message_content", "appendToMessageContent") is not None:
                action_types.append("APPEND_CONTENT")
            elif _get(action, "add_messages_to_task", "addMessagesToTask") is not None:
                action_types.append("ADD_MESSAGE")
            elif _get(action, "tool_call", "toolCall") is not None:
                action_types.append("TOOL_CALL")
            elif _get(action, "tool_response", "toolResponse") is not None:
                action_types.append("TOOL_RESPONSE")
            else:
                action_types.append("UNKNOWN_ACTION")
        
        return f"CLIENT_ACTIONS({', '.join(action_types)})"
    elif "finished" in event_data:
        return "FINISHED"
    else:
        return "UNKNOWN_EVENT"


async def send_protobuf_to_warp_api(
    protobuf_bytes: bytes, show_all_events: bool = True
) -> tuple[str, Optional[str], Optional[str]]:
    """发送protobuf数据到Warp API并获取响应"""
    try:
        logger.info(f"发送 {len(protobuf_bytes)} 字节到Warp API")
        logger.info(f"数据包前32字节 (hex): {protobuf_bytes[:32].hex()}")
        
        warp_url = CONFIG_WARP_URL
        
        logger.info(f"发送请求到: {warp_url}")
        
        conversation_id = None
        task_id = None
        complete_response = []
        all_events = []
        event_count = 0
        
        verify_opt = True
        insecure_env = os.getenv("WARP_INSECURE_TLS", "").lower()
        if insecure_env in ("1", "true", "yes"):
            verify_opt = False
            logger.warning("TLS verification disabled via WARP_INSECURE_TLS for Warp API client")

        async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(60.0), verify=verify_opt, trust_env=True) as client:
            # 在请求前检查配额，如果不足则提前刷新账户
            try:
                from ..core.auth import should_refresh_for_quota
                from ..config.settings import QUOTA_REFRESH_THRESHOLD
                quota_low = await should_refresh_for_quota(threshold=QUOTA_REFRESH_THRESHOLD)
                if quota_low:
                    logger.info("配额不足，提前刷新账户...")
                    try:
                        success = await check_and_refresh_token(force_refresh=True)
                        if success:
                            logger.info("账户刷新成功")
                        else:
                            logger.warning("账户刷新失败")
                    except Exception as e:
                        logger.warning(f"账户刷新失败: {e}")
            except Exception as e:
                logger.warning(f"配额检查异常: {e}")

            # 最多尝试两次：第一次失败且为配额429时申请匿名token并重试一次
            for attempt in range(2):
                jwt = await get_valid_jwt() if attempt == 0 else jwt  # keep existing unless refreshed explicitly
                headers = {
                    "accept": "text/event-stream",
                    "content-type": "application/x-protobuf", 
                    "x-warp-client-version": "v0.2025.08.06.08.12.stable_02",
                    "x-warp-os-category": "Windows",
                    "x-warp-os-name": "Windows", 
                    "x-warp-os-version": "11 (26100)",
                    "authorization": f"Bearer {jwt}",
                    "content-length": str(len(protobuf_bytes)),
                }
                async with client.stream("POST", warp_url, headers=headers, content=protobuf_bytes) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        error_content = error_text.decode('utf-8') if error_text else "No error content"
                        # 检测配额耗尽错误并在第一次失败时尝试刷新账户
                        if response.status_code == 429 and attempt == 0 and (
                            ("No remaining quota" in error_content) or ("No AI requests remaining" in error_content)
                        ):
                            logger.warning("WARP API 返回 429 (配额用尽)。尝试刷新账户并重试一次…")
                            # 先标记当前账户配额用尽
                            mark_current_account_quota_exhausted()
                            try:
                                success = await check_and_refresh_token(force_refresh=True)
                                if success:
                                    jwt = await get_valid_jwt()
                                    # 跳出当前响应并进行下一次尝试
                                    continue
                                else:
                                    logger.error("账户刷新失败，无法重试。")
                            except Exception as e:
                                logger.error(f"账户刷新异常: {e}，无法重试。")
                                logger.error(f"WARP API HTTP ERROR {response.status_code}: {error_content}")
                                return f"❌ Warp API Error (HTTP {response.status_code}): {error_content}", None, None
                        # 其他错误或第二次失败
                        logger.error(f"WARP API HTTP ERROR {response.status_code}: {error_content}")
                        return f"❌ Warp API Error (HTTP {response.status_code}): {error_content}", None, None
                    
                    logger.info(f"✅ 收到HTTP {response.status_code}响应")
                    logger.info("开始处理SSE事件流...")
                    
                    import re as _re
                    def _parse_payload_bytes(data_str: str):
                        s = _re.sub(r"\s+", "", data_str or "")
                        if not s:
                            return None
                        if _re.fullmatch(r"[0-9a-fA-F]+", s or ""):
                            try:
                                return bytes.fromhex(s)
                            except Exception:
                                pass
                        pad = "=" * ((4 - (len(s) % 4)) % 4)
                        try:
                            import base64 as _b64
                            return _b64.urlsafe_b64decode(s + pad)
                        except Exception:
                            try:
                                return _b64.b64decode(s + pad)
                            except Exception:
                                return None
                    
                    current_data = ""
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            payload = line[5:].strip()
                            if not payload:
                                continue
                            if payload == "[DONE]":
                                logger.info("收到[DONE]标记，结束处理")
                                break
                            current_data += payload
                            continue
                        
                        if (line.strip() == "") and current_data:
                            raw_bytes = _parse_payload_bytes(current_data)
                            current_data = ""
                            if raw_bytes is None:
                                logger.debug("跳过无法解析的SSE数据块（非hex/base64或不完整）")
                                continue
                            try:
                                event_data = protobuf_to_dict(raw_bytes, "warp.multi_agent.v1.ResponseEvent")
                            except Exception as parse_error:
                                logger.debug(f"解析事件失败，跳过: {str(parse_error)[:100]}")
                                continue
                            event_count += 1
                            
                            def _get(d: Dict[str, Any], *names: str) -> Any:
                                for n in names:
                                    if isinstance(d, dict) and n in d:
                                        return d[n]
                                return None
                            
                            event_type = _get_event_type(event_data)
                            if show_all_events:
                                all_events.append({"event_number": event_count, "event_type": event_type, "raw_data": event_data})
                            logger.info(f"🔄 Event #{event_count}: {event_type}")
                            if show_all_events:
                                logger.info(f"   📋 Event data: {str(event_data)}...")
                            
                            if "init" in event_data:
                                init_data = event_data["init"]
                                conversation_id = init_data.get("conversation_id", conversation_id)
                                task_id = init_data.get("task_id", task_id)
                                logger.info(f"会话初始化: {conversation_id}")
                                client_actions = _get(event_data, "client_actions", "clientActions")
                                if isinstance(client_actions, dict):
                                    actions = _get(client_actions, "actions", "Actions") or []
                                    for i, action in enumerate(actions):
                                        logger.info(f"   🎯 Action #{i+1}: {list(action.keys())}")
                                        append_data = _get(action, "append_to_message_content", "appendToMessageContent")
                                        if isinstance(append_data, dict):
                                            message = append_data.get("message", {})
                                            agent_output = _get(message, "agent_output", "agentOutput") or {}
                                            text_content = agent_output.get("text", "")
                                            if text_content:
                                                complete_response.append(text_content)
                                                logger.info(f"   📝 Text Fragment: {text_content[:100]}...")
                                        messages_data = _get(action, "add_messages_to_task", "addMessagesToTask")
                                        if isinstance(messages_data, dict):
                                            messages = messages_data.get("messages", [])
                                            task_id = messages_data.get("task_id", messages_data.get("taskId", task_id))
                                            for j, message in enumerate(messages):
                                                logger.info(f"   📨 Message #{j+1}: {list(message.keys())}")
                                                if _get(message, "agent_output", "agentOutput") is not None:
                                                    agent_output = _get(message, "agent_output", "agentOutput") or {}
                                                    text_content = agent_output.get("text", "")
                                                    if text_content:
                                                        complete_response.append(text_content)
                                                        logger.info(f"   📝 Complete Message: {text_content[:100]}...")
                    
                    full_response = "".join(complete_response)
                    logger.info("="*60)
                    logger.info("📊 SSE STREAM SUMMARY")
                    logger.info("="*60)
                    logger.info(f"📈 Total Events Processed: {event_count}")
                    logger.info(f"🆔 Conversation ID: {conversation_id}")
                    logger.info(f"🆔 Task ID: {task_id}")
                    logger.info(f"📝 Response Length: {len(full_response)} characters")
                    logger.info("="*60)
                    if full_response:
                        logger.info(f"✅ Stream processing completed successfully")
                        return full_response, conversation_id, task_id
                    else:
                        logger.warning("⚠️ No text content received in response")
                        return "Warning: No response content received", conversation_id, task_id
    except Exception as e:
        import traceback
        logger.error("="*60)
        logger.error("WARP API CLIENT EXCEPTION")
        logger.error("="*60)
        logger.error(f"Exception Type: {type(e).__name__}")
        logger.error(f"Exception Message: {str(e)}")
        logger.error(f"Request URL: {warp_url if 'warp_url' in locals() else 'Unknown'}")
        logger.error(f"Request Size: {len(protobuf_bytes) if 'protobuf_bytes' in locals() else 'Unknown'}")
        logger.error("Python Traceback:")
        logger.error(traceback.format_exc())
        logger.error("="*60)
        raise


async def send_protobuf_to_warp_api_parsed(protobuf_bytes: bytes) -> tuple[str, Optional[str], Optional[str], list]:
    """发送protobuf数据到Warp API并获取解析后的SSE事件数据"""
    try:
        logger.info(f"发送 {len(protobuf_bytes)} 字节到Warp API (解析模式)")
        logger.info(f"数据包前32字节 (hex): {protobuf_bytes[:32].hex()}")
        
        warp_url = CONFIG_WARP_URL
        
        logger.info(f"发送请求到: {warp_url}")
        
        conversation_id = None
        task_id = None
        complete_response = []
        parsed_events = []
        event_count = 0
        
        verify_opt = True
        insecure_env = os.getenv("WARP_INSECURE_TLS", "").lower()
        if insecure_env in ("1", "true", "yes"):
            verify_opt = False
            logger.warning("TLS verification disabled via WARP_INSECURE_TLS for Warp API client")

        async with httpx.AsyncClient(http2=True, timeout=httpx.Timeout(60.0), verify=verify_opt, trust_env=True) as client:
            # 在请求前检查配额，如果不足则提前刷新账户
            try:
                from ..core.auth import should_refresh_for_quota
                from ..config.settings import QUOTA_REFRESH_THRESHOLD
                quota_low = await should_refresh_for_quota(threshold=QUOTA_REFRESH_THRESHOLD)
                if quota_low:
                    logger.info("配额不足，提前刷新账户...")
                    try:
                        success = await check_and_refresh_token(force_refresh=True)
                        if success:
                            logger.info("账户刷新成功")
                        else:
                            logger.warning("账户刷新失败")
                    except Exception as e:
                        logger.warning(f"账户刷新失败: {e}")
            except Exception as e:
                logger.warning(f"配额检查异常: {e}")

            # 最多尝试两次：第一次失败且为配额429时申请匿名token并重试一次
            for attempt in range(2):
                jwt = await get_valid_jwt() if attempt == 0 else jwt  # keep existing unless refreshed explicitly
                headers = {
                    "accept": "text/event-stream",
                    "content-type": "application/x-protobuf", 
                    "x-warp-client-version": "v0.2025.08.06.08.12.stable_02",
                    "x-warp-os-category": "Windows",
                    "x-warp-os-name": "Windows", 
                    "x-warp-os-version": "11 (26100)",
                    "authorization": f"Bearer {jwt}",
                    "content-length": str(len(protobuf_bytes)),
                }
                async with client.stream("POST", warp_url, headers=headers, content=protobuf_bytes) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        error_content = error_text.decode('utf-8') if error_text else "No error content"
                        # 检测配额耗尽错误并在第一次失败时尝试刷新账户
                        if response.status_code == 429 and attempt == 0 and (
                            ("No remaining quota" in error_content) or ("No AI requests remaining" in error_content)
                        ):
                            logger.warning("WARP API 返回 429 (配额用尽, 解析模式)。尝试刷新账户并重试一次…")
                            # 先标记当前账户配额用尽
                            mark_current_account_quota_exhausted()
                            try:
                                success = await check_and_refresh_token(force_refresh=True)
                                if success:
                                    jwt = await get_valid_jwt()
                                    # 跳出当前响应并进行下一次尝试
                                    continue
                                else:
                                    logger.error("账户刷新失败，无法重试 (解析模式)。")
                            except Exception as e:
                                logger.error(f"账户刷新异常: {e}，无法重试 (解析模式)。")
                                logger.error(f"WARP API HTTP ERROR (解析模式) {response.status_code}: {error_content}")
                                return f"❌ Warp API Error (HTTP {response.status_code}): {error_content}", None, None, []
                        # 其他错误或第二次失败
                        logger.error(f"WARP API HTTP ERROR (解析模式) {response.status_code}: {error_content}")
                        return f"❌ Warp API Error (HTTP {response.status_code}): {error_content}", None, None, []
                    
                    logger.info(f"✅ 收到HTTP {response.status_code}响应 (解析模式)")
                    logger.info("开始处理SSE事件流...")
                    
                    import re as _re2
                    def _parse_payload_bytes2(data_str: str):
                        s = _re2.sub(r"\s+", "", data_str or "")
                        if not s:
                            return None
                        if _re2.fullmatch(r"[0-9a-fA-F]+", s or ""):
                            try:
                                return bytes.fromhex(s)
                            except Exception:
                                pass
                        pad = "=" * ((4 - (len(s) % 4)) % 4)
                        try:
                            import base64 as _b642
                            return _b642.urlsafe_b64decode(s + pad)
                        except Exception:
                            try:
                                return _b642.b64decode(s + pad)
                            except Exception:
                                return None
                    
                    current_data = ""
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            payload = line[5:].strip()
                            if not payload:
                                continue
                            if payload == "[DONE]":
                                logger.info("收到[DONE]标记，结束处理")
                                break
                            current_data += payload
                            continue
                        
                        if (line.strip() == "") and current_data:
                            raw_bytes = _parse_payload_bytes2(current_data)
                            current_data = ""
                            if raw_bytes is None:
                                logger.debug("跳过无法解析的SSE数据块（非hex/base64或不完整）")
                                continue
                            try:
                                event_data = protobuf_to_dict(raw_bytes, "warp.multi_agent.v1.ResponseEvent")
                                event_count += 1
                                event_type = _get_event_type(event_data)
                                parsed_event = {"event_number": event_count, "event_type": event_type, "parsed_data": event_data}
                                parsed_events.append(parsed_event)
                                logger.info(f"🔄 Event #{event_count}: {event_type}")
                                logger.debug(f"   📋 Event data: {str(event_data)}...")
                                
                                def _get(d: Dict[str, Any], *names: str) -> Any:
                                    for n in names:
                                        if isinstance(d, dict) and n in d:
                                            return d[n]
                                    return None
                                
                                if "init" in event_data:
                                    init_data = event_data["init"]
                                    conversation_id = init_data.get("conversation_id", conversation_id)
                                    task_id = init_data.get("task_id", task_id)
                                    logger.info(f"会话初始化: {conversation_id}")
                                
                                client_actions = _get(event_data, "client_actions", "clientActions")
                                if isinstance(client_actions, dict):
                                    actions = _get(client_actions, "actions", "Actions") or []
                                    for i, action in enumerate(actions):
                                        logger.info(f"   🎯 Action #{i+1}: {list(action.keys())}")
                                        append_data = _get(action, "append_to_message_content", "appendToMessageContent")
                                        if isinstance(append_data, dict):
                                            message = append_data.get("message", {})
                                            agent_output = _get(message, "agent_output", "agentOutput") or {}
                                            text_content = agent_output.get("text", "")
                                            if text_content:
                                                complete_response.append(text_content)
                                                logger.info(f"   📝 Text Fragment: {text_content[:100]}...")
                                        messages_data = _get(action, "add_messages_to_task", "addMessagesToTask")
                                        if isinstance(messages_data, dict):
                                            messages = messages_data.get("messages", [])
                                            task_id = messages_data.get("task_id", messages_data.get("taskId", task_id))
                                            for j, message in enumerate(messages):
                                                logger.info(f"   📨 Message #{j+1}: {list(message.keys())}")
                                                if _get(message, "agent_output", "agentOutput") is not None:
                                                    agent_output = _get(message, "agent_output", "agentOutput") or {}
                                                    text_content = agent_output.get("text", "")
                                                    if text_content:
                                                        complete_response.append(text_content)
                                                        logger.info(f"   📝 Complete Message: {text_content[:100]}...")
                            except Exception as parse_err:
                                logger.debug(f"解析事件失败，跳过: {str(parse_err)[:100]}")
                                continue
                    
                    full_response = "".join(complete_response)
                    logger.info("="*60)
                    logger.info("📊 SSE STREAM SUMMARY (解析模式)")
                    logger.info("="*60)
                    logger.info(f"📈 Total Events Processed: {event_count}")
                    logger.info(f"🆔 Conversation ID: {conversation_id}")
                    logger.info(f"🆔 Task ID: {task_id}")
                    logger.info(f"📝 Response Length: {len(full_response)} characters")
                    logger.info(f"🎯 Parsed Events Count: {len(parsed_events)}")
                    logger.info("="*60)
                    
                    logger.info(f"✅ Stream processing completed successfully (解析模式)")
                    return full_response, conversation_id, task_id, parsed_events
    except Exception as e:
        import traceback
        logger.error("="*60)
        logger.error("WARP API CLIENT EXCEPTION (解析模式)")
        logger.error("="*60)
        logger.error(f"Exception Type: {type(e).__name__}")
        logger.error(f"Exception Message: {str(e)}")
        logger.error(f"Request URL: {warp_url if 'warp_url' in locals() else 'Unknown'}")
        logger.error(f"Request Size: {len(protobuf_bytes) if 'protobuf_bytes' in locals() else 'Unknown'}")
        logger.error("Python Traceback:")
        logger.error(traceback.format_exc())
        logger.error("="*60)
        raise