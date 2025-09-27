#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT Authentication for Warp API

Handles JWT token management, refresh, and validation.
Integrates functionality from refresh_jwt.py.
"""
import base64
import json
import os
import time
from pathlib import Path
import httpx
import asyncio
from dotenv import load_dotenv, set_key

from ..config.settings import REFRESH_TOKEN_B64, REFRESH_URL, CLIENT_VERSION, OS_CATEGORY, OS_NAME, OS_VERSION, QUOTA_REFRESH_THRESHOLD
from .logging import logger, log


def decode_jwt_payload(token: str) -> dict:
    """Decode JWT payload to check expiration"""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return {}
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += '=' * padding
        payload_bytes = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode('utf-8'))
        return payload
    except Exception as e:
        logger.debug(f"Error decoding JWT: {e}")
        return {}


def is_token_expired(token: str, buffer_minutes: int = 5) -> bool:
    payload = decode_jwt_payload(token)
    if not payload or 'exp' not in payload:
        return True
    expiry_time = payload['exp']
    current_time = time.time()
    buffer_time = buffer_minutes * 60
    return (expiry_time - current_time) <= buffer_time


async def refresh_jwt_token() -> dict:
    """Refresh the JWT token using the refresh token.

    Prefers environment variable WARP_REFRESH_TOKEN when present; otherwise
    falls back to the baked-in REFRESH_TOKEN_B64 payload.

    Returns:
        dict: Token data with additional error_type field if failed
    """
    logger.info("Refreshing JWT token...")
    # Prefer dynamic refresh token from environment if present
    env_refresh = os.getenv("WARP_REFRESH_TOKEN")
    if env_refresh:
        payload = f"grant_type=refresh_token&refresh_token={env_refresh}".encode("utf-8")
    else:
        payload = base64.b64decode(REFRESH_TOKEN_B64)
    headers = {
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
        "content-type": "application/x-www-form-urlencoded",
        "accept": "*/*",
        "accept-encoding": "gzip, br",
        "content-length": str(len(payload))
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                REFRESH_URL,
                headers=headers,
                content=payload
            )
            if response.status_code == 200:
                token_data = response.json()
                logger.info("Token refresh successful")
                # 保存ID token（如果存在）用于配额查询
                if "id_token" in token_data:
                    update_env_id_token(token_data["id_token"])
                return token_data
            else:
                logger.error(f"Token refresh failed: {response.status_code}")
                logger.error(f"Response: {response.text}")

                # 判断错误类型
                error_type = "refresh_failed"  # 默认
                response_text = response.text.lower()

                if response.status_code == 401:
                    error_type = "invalid_token"
                elif response.status_code == 429:
                    if "no remaining quota" in response_text or "no ai requests remaining" in response_text:
                        error_type = "quota_exhausted"
                elif "invalid_grant" in response_text or "invalid_token" in response_text:
                    error_type = "invalid_token"
                elif "refresh token is invalid" in response_text:
                    error_type = "invalid_token"

                return {"error_type": error_type}
    except Exception as e:
        logger.error(f"Error refreshing token: {e}")
        return {"error_type": "refresh_failed"}


def update_env_file(new_jwt: str) -> bool:
    env_path = Path(".env")
    try:
        set_key(str(env_path), "WARP_JWT", new_jwt)
        logger.info("Updated .env file with new JWT token")
        return True
    except Exception as e:
        logger.error(f"Error updating .env file: {e}")
        return False


def update_env_id_token(id_token: str) -> bool:
    """更新环境变量中的ID token"""
    env_path = Path(".env")
    try:
        set_key(str(env_path), "WARP_ID_TOKEN", id_token)
        logger.info("Updated .env file with new ID token")
        return True
    except Exception as e:
        logger.error(f"Error updating ID token in .env file: {e}")
        return False


def update_env_refresh_token(refresh_token: str) -> bool:
    env_path = Path(".env")
    try:
        set_key(str(env_path), "WARP_REFRESH_TOKEN", refresh_token)
        logger.info("Updated .env with WARP_REFRESH_TOKEN")
        return True
    except Exception as e:
        logger.error(f"Error updating .env WARP_REFRESH_TOKEN: {e}")
        return False


# ============ File-based JWT refresh functions ============

def load_accounts_from_file(file_path: str) -> list:
    """从JSON文件加载账户列表，并初始化账户状态"""
    try:
        if not os.path.exists(file_path):
            logger.warning(f"账户文件不存在: {file_path}")
            return []

        with open(file_path, 'r', encoding='utf-8') as f:
            accounts = json.load(f)

        if not isinstance(accounts, list):
            logger.error(f"账户文件格式错误，应为数组: {file_path}")
            return []

        # 初始化账户状态字段
        updated = False
        for account in accounts:
            if 'account_status' not in account:
                account['account_status'] = 'available'
                updated = True

        # 如果有更新，保存文件
        if updated:
            save_accounts_to_file(file_path, accounts)
            logger.info(f"已初始化账户状态字段: {file_path}")

        logger.info(f"从文件加载了 {len(accounts)} 个账户: {file_path}")
        return accounts
    except Exception as e:
        logger.error(f"加载账户文件失败: {e}")
        return []


def save_accounts_to_file(file_path: str, accounts: list) -> bool:
    """保存账户列表到JSON文件"""
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)

        logger.info(f"账户文件保存成功: {file_path}")
        return True
    except Exception as e:
        logger.error(f"保存账户文件失败: {e}")
        return False


def get_current_account_from_file(file_path: str) -> dict:
    """从文件中获取当前可用的账户"""
    accounts = load_accounts_from_file(file_path)
    if not accounts:
        return {}

    # 优先选择状态为available且有refresh_token的账户
    for account in accounts:
        if (account.get('refresh_token') and
            account.get('account_status', 'available') == 'available'):
            logger.info(f"选择可用账户: {account.get('email', 'unknown')}")
            return account

    # 如果没有可用账户，记录状态信息
    available_count = sum(1 for acc in accounts if acc.get('account_status', 'available') == 'available')
    exhausted_count = sum(1 for acc in accounts if acc.get('account_status') == 'quota_exhausted')
    failed_count = sum(1 for acc in accounts if acc.get('account_status') == 'refresh_failed')
    invalid_count = sum(1 for acc in accounts if acc.get('account_status') == 'invalid_token')

    logger.warning(f"没有可用账户 - 可用:{available_count}, 配额用尽:{exhausted_count}, 刷新失败:{failed_count}, token无效:{invalid_count}")
    return {}


def update_account_status(file_path: str, email: str, status: str) -> bool:
    """更新指定账户的状态"""
    try:
        accounts = load_accounts_from_file(file_path)
        if not accounts:
            return False

        # 查找并更新指定账户的状态
        updated = False
        for account in accounts:
            if account.get('email') == email:
                old_status = account.get('account_status', 'available')
                account['account_status'] = status
                logger.info(f"账户状态更新: {email} {old_status} → {status}")
                updated = True
                break

        if updated:
            return save_accounts_to_file(file_path, accounts)
        else:
            logger.warning(f"未找到账户: {email}")
            return False
    except Exception as e:
        logger.error(f"更新账户状态失败: {e}")
        return False


async def refresh_from_file(file_path: str) -> bool:
    """从文件中获取refresh_token并刷新JWT"""
    account = get_current_account_from_file(file_path)
    if not account or not account.get('refresh_token'):
        logger.error("无法从文件获取有效的refresh_token")
        return False

    refresh_token = account['refresh_token']
    email = account.get('email', 'unknown')
    logger.info(f"使用文件中的refresh_token刷新JWT: {email}")

    # 设置环境变量
    os.environ["WARP_REFRESH_TOKEN"] = refresh_token

    try:
        # 使用现有的刷新逻辑
        token_data = await refresh_jwt_token()
        if token_data and "access_token" in token_data:
            new_jwt = token_data["access_token"]
            if not is_token_expired(new_jwt, buffer_minutes=0):
                logger.info("文件模式JWT刷新成功")
                # 刷新成功后，将refresh_token保存到.env文件
                if update_env_refresh_token(refresh_token):
                    logger.info("已将文件中的refresh_token保存到.env文件")
                # 刷新成功，保持账户状态为available
                update_account_status(file_path, email, 'available')
                return update_env_file(new_jwt)
            else:
                logger.warning("文件模式刷新的JWT无效或已过期")
                # JWT立即过期，标记为token无效
                update_account_status(file_path, email, 'invalid_token')
                return False
        elif token_data and "error_type" in token_data:
            # 根据具体错误类型更新账户状态
            error_type = token_data["error_type"]
            logger.error(f"文件模式JWT刷新失败，错误类型: {error_type}")
            update_account_status(file_path, email, error_type)
            return False
        else:
            logger.error("文件模式JWT刷新失败")
            # 未知错误，标记为刷新失败
            update_account_status(file_path, email, 'refresh_failed')
            return False
    except Exception as e:
        logger.error(f"文件模式刷新异常: {e}")
        # 异常情况，标记为刷新失败
        update_account_status(file_path, email, 'refresh_failed')
        return False


def mark_current_account_quota_exhausted() -> bool:
    """标记当前使用的账户配额已用尽"""
    local_jwt_filepath = os.getenv("LOCAL_JWT_FILEPATH")
    if not local_jwt_filepath:
        logger.debug("未配置LOCAL_JWT_FILEPATH，跳过账户状态更新")
        return False

    # 获取当前环境变量中的refresh_token
    current_refresh_token = os.getenv("WARP_REFRESH_TOKEN")
    if not current_refresh_token:
        logger.debug("未找到当前refresh_token，跳过账户状态更新")
        return False

    try:
        accounts = load_accounts_from_file(local_jwt_filepath)
        if not accounts:
            return False

        # 查找匹配的账户并标记为配额用尽
        for account in accounts:
            if account.get('refresh_token') == current_refresh_token:
                email = account.get('email', 'unknown')
                logger.info(f"标记账户配额用尽: {email}")
                return update_account_status(local_jwt_filepath, email, 'quota_exhausted')

        logger.warning("未找到匹配当前refresh_token的账户")
        return False
    except Exception as e:
        logger.error(f"标记账户配额用尽失败: {e}")
        return False


async def check_and_refresh_token(force_refresh: bool = False) -> bool:
    # 重新加载环境变量，防止并发刷新时的状态不一致
    from dotenv import load_dotenv as _load
    _load(override=True)

    current_jwt = os.getenv("WARP_JWT")
    if not current_jwt:
        logger.warning("No JWT token found in environment")
        # 检查是否配置了文件路径
        local_jwt_filepath = os.getenv("LOCAL_JWT_FILEPATH")
        if local_jwt_filepath:
            logger.info("尝试从文件刷新JWT...")
            if await refresh_from_file(local_jwt_filepath):
                return True

        token_data = await refresh_jwt_token()
        if token_data and "access_token" in token_data:
            return update_env_file(token_data["access_token"])
        return False

    logger.debug("Checking current JWT token expiration...")
    token_expired = is_token_expired(current_jwt, buffer_minutes=15)

    # 检查配额是否不足
    quota_low = await should_refresh_for_quota(threshold=QUOTA_REFRESH_THRESHOLD)

    if force_refresh and not quota_low:
        logger.info("收到强制刷新请求，按配额耗尽流程处理")
        quota_low = True

    if token_expired or quota_low:
        if token_expired:
            logger.info("JWT token is expired or expiring soon, refreshing...")
        if quota_low:
            logger.info("配额不足，需要刷新...")

        # 如果配额不足，优先使用文件刷新（如果配置了），否则使用匿名账户刷新
        if quota_low:
            local_jwt_filepath = os.getenv("LOCAL_JWT_FILEPATH")
            if local_jwt_filepath:
                logger.info("配额不足，尝试从文件刷新...")
                # 先标记当前账户配额用尽，这样下次选择时会跳过这个账户
                mark_current_account_quota_exhausted()
                try:
                    if await refresh_from_file(local_jwt_filepath):
                        logger.info("文件刷新成功")
                        return True
                    else:
                        logger.warning("文件刷新失败，尝试匿名刷新")
                except Exception as e:
                    logger.warning(f"文件刷新异常: {e}，尝试匿名刷新")

            # 如果没有配置文件路径或文件刷新失败，使用匿名刷新
            try:
                new_jwt = await acquire_anonymous_access_token()
                if new_jwt and not is_token_expired(new_jwt, buffer_minutes=0):
                    logger.info("匿名账户刷新成功")
                    return True
                else:
                    logger.warning("匿名账户刷新失败，尝试普通刷新")
            except Exception as e:
                logger.warning(f"匿名账户刷新异常: {e}，尝试普通刷新")

        # 普通token刷新
        token_data = await refresh_jwt_token()
        if token_data and "access_token" in token_data:
            new_jwt = token_data["access_token"]
            if not is_token_expired(new_jwt, buffer_minutes=0):
                logger.info("New token is valid")
                return update_env_file(new_jwt)
            else:
                logger.warning("New token appears to be invalid or expired")
                return False
        else:
            logger.error("Failed to get new token from refresh")
            return False
    else:
        payload = decode_jwt_payload(current_jwt)
        if payload and 'exp' in payload:
            expiry_time = payload['exp']
            time_left = expiry_time - time.time()
            hours_left = time_left / 3600
            logger.debug(f"Current token is still valid ({hours_left:.1f} hours remaining)")
        else:
            logger.debug("Current token appears valid")
        return True


async def get_valid_jwt() -> str:
    from dotenv import load_dotenv as _load
    _load(override=True)
    jwt = os.getenv("WARP_JWT")
    if not jwt:
        logger.info("No JWT token found, attempting to refresh...")
        if await check_and_refresh_token():
            _load(override=True)
            jwt = os.getenv("WARP_JWT")
        if not jwt:
            raise RuntimeError("WARP_JWT is not set and refresh failed")
    if is_token_expired(jwt, buffer_minutes=2):
        logger.info("JWT token is expired or expiring soon, attempting to refresh...")
        if await check_and_refresh_token():
            _load(override=True)
            jwt = os.getenv("WARP_JWT")
            if not jwt or is_token_expired(jwt, buffer_minutes=0):
                logger.warning("Warning: New token has short expiry but proceeding anyway")
        else:
            logger.warning("Warning: JWT token refresh failed, trying to use existing token")
    return jwt


def get_jwt_token() -> str:
    from dotenv import load_dotenv as _load
    _load()
    return os.getenv("WARP_JWT", "")


async def refresh_jwt_if_needed() -> bool:
    try:
        return await check_and_refresh_token()
    except Exception as e:
        logger.error(f"JWT refresh failed: {e}")
        return False


# ============ Anonymous token acquisition (quota refresh) ============

_ANON_GQL_URL = "https://app.warp.dev/graphql/v2?op=CreateAnonymousUser"
_IDENTITY_TOOLKIT_BASE = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken"


def _extract_google_api_key_from_refresh_url() -> str:
    try:
        # REFRESH_URL like: https://app.warp.dev/proxy/token?key=API_KEY
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(REFRESH_URL)
        qs = parse_qs(parsed.query)
        key = qs.get("key", [""])[0]
        return key
    except Exception:
        return ""


async def _create_anonymous_user() -> dict:
    headers = {
        "accept-encoding": "gzip, br",
        "content-type": "application/json",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    # GraphQL payload per anonymous.MD
    query = (
        "mutation CreateAnonymousUser($input: CreateAnonymousUserInput!, $requestContext: RequestContext!) {\n"
        "  createAnonymousUser(input: $input, requestContext: $requestContext) {\n"
        "    __typename\n"
        "    ... on CreateAnonymousUserOutput {\n"
        "      expiresAt\n"
        "      anonymousUserType\n"
        "      firebaseUid\n"
        "      idToken\n"
        "      isInviteValid\n"
        "      responseContext { serverVersion }\n"
        "    }\n"
        "    ... on UserFacingError {\n"
        "      error { __typename message }\n"
        "      responseContext { serverVersion }\n"
        "    }\n"
        "  }\n"
        "}\n"
    )
    variables = {
        "input": {
            "anonymousUserType": "NATIVE_CLIENT_ANONYMOUS_USER_FEATURE_GATED",
            "expirationType": "NO_EXPIRATION",
            "referralCode": None
        },
        "requestContext": {
            "clientContext": {"version": CLIENT_VERSION},
            "osContext": {
                "category": OS_CATEGORY,
                "linuxKernelVersion": None,
                "name": OS_NAME,
                "version": OS_VERSION,
            }
        }
    }
    body = {"query": query, "variables": variables, "operationName": "CreateAnonymousUser"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(_ANON_GQL_URL, headers=headers, json=body)
        if resp.status_code != 200:
            raise RuntimeError(f"CreateAnonymousUser failed: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        return data


async def _exchange_id_token_for_refresh_token(id_token: str) -> dict:
    key = _extract_google_api_key_from_refresh_url()
    url = f"{_IDENTITY_TOOLKIT_BASE}?key={key}" if key else f"{_IDENTITY_TOOLKIT_BASE}?key=AIzaSyBdy3O3S9hrdayLJxJ7mriBR4qgUaUygAs"
    headers = {
        "accept-encoding": "gzip, br",
        "content-type": "application/x-www-form-urlencoded",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }
    form = {
        "returnSecureToken": "true",
        "token": id_token,
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(url, headers=headers, data=form)
        if resp.status_code != 200:
            raise RuntimeError(f"signInWithCustomToken failed: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()


async def acquire_anonymous_access_token() -> str:
    """Acquire a new anonymous access token (quota refresh) and persist to .env.

    Returns the new access token string. Raises on failure.
    """
    logger.info("Acquiring anonymous access token via GraphQL + Identity Toolkit…")
    data = await _create_anonymous_user()
    id_token = None
    try:
        id_token = data["data"]["createAnonymousUser"].get("idToken")
    except Exception:
        pass
    if not id_token:
        raise RuntimeError(f"CreateAnonymousUser did not return idToken: {data}")

    signin = await _exchange_id_token_for_refresh_token(id_token)
    refresh_token = signin.get("refreshToken")
    if not refresh_token:
        raise RuntimeError(f"signInWithCustomToken did not return refreshToken: {signin}")

    # Persist refresh token for future time-based refreshes
    update_env_refresh_token(refresh_token)

    # Now call Warp proxy token endpoint to get access_token using this refresh token
    payload = f"grant_type=refresh_token&refresh_token={refresh_token}".encode("utf-8")
    headers = {
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
        "content-type": "application/x-www-form-urlencoded",
        "accept": "*/*",
        "accept-encoding": "gzip, br",
        "content-length": str(len(payload))
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        resp = await client.post(REFRESH_URL, headers=headers, content=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Acquire access_token failed: HTTP {resp.status_code} {resp.text[:200]}")
        token_data = resp.json()
        access = token_data.get("access_token")
        if not access:
            raise RuntimeError(f"No access_token in response: {token_data}")
        update_env_file(access)
        return access


def print_token_info():
    current_jwt = os.getenv("WARP_JWT")
    if not current_jwt:
        logger.info("No JWT token found")
        return
    payload = decode_jwt_payload(current_jwt)
    if not payload:
        logger.info("Cannot decode JWT token")
        return
    logger.info("=== JWT Token Information ===")
    if 'email' in payload:
        logger.info(f"Email: {payload['email']}")
    if 'user_id' in payload:
        logger.info(f"User ID: {payload['user_id']}")


async def get_valid_id_token() -> str:
    """获取有效的ID token，类似get_valid_jwt的逻辑"""
    from dotenv import load_dotenv as _load
    _load(override=True)
    id_token = os.getenv("WARP_ID_TOKEN")

    if not id_token:
        logger.info("No ID token found, attempting to refresh...")
        # 没有ID token，尝试刷新获取
        token_data = await refresh_jwt_token()  # 这会自动保存ID token
        if token_data:
            _load(override=True)
            id_token = os.getenv("WARP_ID_TOKEN")
        if not id_token:
            logger.warning("Failed to obtain ID token after refresh")
            return ""

    if id_token and is_token_expired(id_token, buffer_minutes=2):
        logger.info("ID token is expired or expiring soon, attempting to refresh...")
        # ID token即将过期，刷新获取新的
        token_data = await refresh_jwt_token()  # 刷新时会获取新的ID token
        if token_data:
            _load(override=True)
            id_token = os.getenv("WARP_ID_TOKEN")
            if not id_token or is_token_expired(id_token, buffer_minutes=0):
                logger.warning("Warning: New ID token has short expiry but proceeding anyway")
        else:
            logger.warning("Warning: ID token refresh failed, trying to use existing token")

    return id_token or ""


async def get_quota_info() -> dict:
    """获取当前账户的配额信息

    Returns:
        dict: 包含配额信息的字典，格式如下：
        {
            "requestLimit": 150,
            "requestsUsedSinceLastRefresh": 4,
            "nextRefreshTime": "2025-10-14T00:30:28.13715Z"
        }
    """
    id_token = await get_valid_id_token()
    if not id_token:
        logger.warning("No valid ID token available, cannot get quota info")
        return {}

    url = "https://app.warp.dev/graphql/v2?op=GetRequestLimitInfo"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {id_token}",
        "x-warp-client-version": CLIENT_VERSION,
        "x-warp-os-category": OS_CATEGORY,
        "x-warp-os-name": OS_NAME,
        "x-warp-os-version": OS_VERSION,
    }

    query_data = {
        "query": "query GetRequestLimitInfo($requestContext: RequestContext!) { user(requestContext: $requestContext) { __typename ... on UserOutput { user { requestLimitInfo { nextRefreshTime requestLimit requestsUsedSinceLastRefresh } } } } }",
        "variables": {
            "requestContext": {
                "clientContext": {"version": CLIENT_VERSION},
                "osContext": {
                    "category": OS_CATEGORY,
                    "linuxKernelVersion": None,
                    "name": OS_NAME,
                    "version": OS_VERSION
                }
            }
        },
        "operationName": "GetRequestLimitInfo"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=query_data)
            if response.status_code == 200:
                data = response.json()
                try:
                    quota_info = data["data"]["user"]["user"]["requestLimitInfo"]
                    logger.info(f"配额信息: 限制={quota_info['requestLimit']}, 已用={quota_info['requestsUsedSinceLastRefresh']}")
                    return quota_info
                except (KeyError, TypeError) as e:
                    logger.error(f"解析配额信息失败: {e}, 响应: {data}")
                    return {}
            else:
                logger.error(f"获取配额信息失败: {response.status_code}, {response.text}")
                return {}
    except Exception as e:
        logger.error(f"获取配额信息异常: {e}")
        return {}


async def should_refresh_for_quota(threshold: int = 0) -> bool:
    """检查是否应该因为配额不足而刷新账户

    Args:
        threshold: 配额阈值，当剩余配额少于此值时返回True。设置为0表示禁用配额检查

    Returns:
        bool: 是否需要刷新
    """
    # 如果阈值为0，表示禁用配额检查
    if threshold == 0:
        logger.debug("配额检查已禁用 (threshold=0)")
        return False

    try:
        quota_info = await get_quota_info()
        if not quota_info:
            logger.warning("无法获取配额信息，跳过配额检查")
            return False

        request_limit = quota_info.get("requestLimit", 0)
        requests_used = quota_info.get("requestsUsedSinceLastRefresh", 0)
        remaining = request_limit - requests_used

        logger.info(f"配额检查: 总限制={request_limit}, 已使用={requests_used}, 剩余={remaining}")

        if remaining <= threshold:
            logger.warning(f"配额不足！剩余={remaining} <= 阈值={threshold}，需要刷新账户")
            return True
        else:
            logger.info(f"配额充足: 剩余={remaining} > 阈值={threshold}")
            return False

    except Exception as e:
        logger.error(f"配额检查异常: {e}")
        return False