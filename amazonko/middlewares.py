# Define here the models for your spider middleware
# 在此定义爬虫中间件的模型
import random
import logging
import base64 # 用于代理认证编码
from urllib.parse import urlparse # 用于解析代理 URL
from scrapy import signals
from scrapy.exceptions import NotConfigured
from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message
# 导入 TunnelError 以便在 process_exception 中检查
from scrapy.core.downloader.handlers.http11 import TunnelError

logger = logging.getLogger(__name__)

# --- 通用 HTTP 代理中间件 ---
class CustomHttpProxyMiddleware:
    """
    通用代理中间件，支持从 settings.py 中的 PROXY_CONFIG 配置多个提供商。
    - 为标准 Scrapy HTTPS 请求添加 Proxy-Authorization 头。
    - 为 Playwright 请求设置 meta['playwright_page_proxy']。
    - 处理特定提供商的额外请求头 (如 16yun 的 Proxy-Tunnel, Connection)。
    """
    def __init__(self, settings):
        # 获取所有代理配置
        self.proxy_configs = settings.getlist('PROXY_CONFIG')
        # 过滤出已启用的配置
        self.enabled_proxies = [p for p in self.proxy_configs if p.get('enabled')]

        if not self.enabled_proxies:
            raise NotConfigured("没有在 PROXY_CONFIG 中找到启用的代理配置。")

        logger.info(f"Initialized CustomHttpProxyMiddleware with {len(self.enabled_proxies)} enabled proxy configurations.")

        # 预计算 Basic Auth 头 (如果用户名密码直接可用)
        self.proxy_auth_headers = {} # 存储 {完整代理URL: 认证头bytes}
        for config in self.enabled_proxies:
            username = config.get('username')
            password = config.get('password')
            if not username or not password: continue # 跳过没有完整认证信息的配置

            user_pass = f"{username}:{password}"
            encoded_user_pass = base64.b64encode(user_pass.encode()).decode('latin-1')
            auth_header_bytes = b'Basic ' + encoded_user_pass.encode('latin-1')

            # 根据配置类型构建代理 URL 并存储认证头
            provider_type = config.get('provider_type')
            endpoints = config.get('endpoints', [])
            proxy_url_format = config.get('proxy_url_format')
            host = config.get('host')
            port = config.get('port')

            if provider_type == 'oxylabs_isp': # Oxylabs 直接提供完整 URL
                for endpoint_url in endpoints:
                    # 格式化 URL (替换用户名密码占位符)
                    formatted_url = endpoint_url.format(username=username, password=password)
                    self.proxy_auth_headers[formatted_url] = auth_header_bytes
            elif proxy_url_format and host and port: # 需要构建 URL (如 16yun)
                proxy_url = proxy_url_format.format(username=username, password=password, host=host, port=port)
                self.proxy_auth_headers[proxy_url] = auth_header_bytes
            elif endpoints: # 尝试直接使用 endpoint 作为 key (如果它是完整 URL)
                 for endpoint_url in endpoints:
                     if "://" in endpoint_url: # 简单判断是否是 URL
                          # 假设 endpoint 已包含认证或无需认证，或者需要后续处理
                          # 这里可能需要根据具体情况调整，但至少为已知格式的 URL 存储了头
                          # 对于 Oxylabs 这种已格式化的，这里会重复存储，但不影响
                          self.proxy_auth_headers[endpoint_url] = auth_header_bytes

        logger.debug(f"Pre-calculated auth headers for: {list(self.proxy_auth_headers.keys())}")


    @classmethod
    def from_crawler(cls, crawler):
        # Scrapy 调用此方法来创建中间件实例
        return cls(crawler.settings)

    def _get_random_proxy(self):
        """随机选择一个启用的代理配置，并返回其完整代理 URL 和配置字典。"""
        if not self.enabled_proxies: return None, None # 没有可用代理

        chosen_config = random.choice(self.enabled_proxies)
        provider_type = chosen_config.get('provider_type', 'unknown')
        endpoints = chosen_config.get('endpoints', [])
        if not endpoints: return None, None # 配置无效

        # 随机选择一个端点
        endpoint = random.choice(endpoints)

        # 构建完整的代理 URL
        proxy_url = None
        username = chosen_config.get('username')
        password = chosen_config.get('password')
        proxy_url_format = chosen_config.get('proxy_url_format')
        host = chosen_config.get('host')
        port = chosen_config.get('port')

        # 优先使用格式化模板构建
        if proxy_url_format and host and port and username and password:
             proxy_url = proxy_url_format.format(username=username, password=password, host=host, port=port)
        # 其次，如果 endpoint 本身包含协议头，认为它是完整 URL (适用于 Oxylabs)
        elif "://" in endpoint:
             # 如果 endpoint 模板包含占位符，进行替换
             if "{username}" in endpoint and "{password}" in endpoint:
                  proxy_url = endpoint.format(username=username, password=password)
             else:
                  proxy_url = endpoint # 假设 endpoint 已包含认证或无需认证
        else: # 其他情况无法确定 URL
             logger.error(f"无法为提供商 {provider_type} 构建有效的代理 URL (endpoint: {endpoint})")
             return None, None

        return proxy_url, chosen_config # 返回完整 URL 和配置字典

    def process_request(self, request, spider):
        # 处理请求，分配代理和认证

        # *** 增加日志：检查请求是否来自图片管道或需要代理 ***
        # 图片管道发出的请求通常没有 'playwright' meta
        is_playwright_request = request.meta.get('playwright', False)
        needs_proxy = True # 默认所有请求都需要代理，除非特殊标记
        # 可以添加逻辑，例如根据 URL 或 meta 标记某些请求不需要代理
        # if 'dont_proxy' in request.meta: needs_proxy = False

        # 如果请求已设置有效代理，并且我们不需要强制更换，则跳过
        if request.meta.get('proxy') and '://' in request.meta['proxy'] and needs_proxy:
            logger.debug(f"Request already has proxy: {request.meta['proxy']}, skipping assignment.")
            proxy_url = request.meta['proxy']
            provider_type = "unknown (preset)" # 无法轻易反查配置
        elif needs_proxy:
            # 获取一个随机代理及其配置
            proxy_url, proxy_config = self._get_random_proxy()
            if not proxy_url or not proxy_config:
                logger.error("未能获取有效代理，请求将不使用代理。")
                return # 不使用代理
            request.meta['proxy'] = proxy_url # 设置 Scrapy 使用的代理 meta
            provider_type = proxy_config.get('provider_type', 'unknown')
            logger.debug(f"[{provider_type}] Using proxy: {proxy_url} for request: {request.url}")

            # --- 处理特定提供商的请求头 ---
            extra_headers = proxy_config.get('headers', {})
            for header, value in extra_headers.items():
                if header == 'Proxy-Tunnel' and value == 'random':
                    tunnel_id = str(random.randint(1, 10000))
                    request.headers['Proxy-Tunnel'] = tunnel_id
                    logger.debug(f"[{provider_type}] Added header: Proxy-Tunnel={tunnel_id}")
                else:
                    request.headers[header] = value
                    logger.debug(f"[{provider_type}] Added header: {header}={value}")
        else:
            # 请求不需要代理
            logger.debug(f"Request {request.url} does not require proxy, skipping assignment.")
            proxy_url = None # 明确无代理
            provider_type = None

        # --- 处理 Playwright ---
        if is_playwright_request:
            if 'playwright_page_proxy' not in request.meta and proxy_url:
                try:
                    parsed_proxy = urlparse(proxy_url)
                    if parsed_proxy.hostname and parsed_proxy.port and parsed_proxy.username and parsed_proxy.password:
                        playwright_proxy_config = { "server": f"{parsed_proxy.scheme}://{parsed_proxy.hostname}:{parsed_proxy.port}", "username": parsed_proxy.username, "password": parsed_proxy.password }
                        request.meta['playwright_page_proxy'] = playwright_proxy_config
                        logger.debug(f"[{provider_type or 'preset'}] Passing proxy config to Playwright: {playwright_proxy_config['server']}")
                    else: logger.error(f"[{provider_type or 'preset'}] Proxy URL {proxy_url} missing parts for Playwright config.")
                except Exception as e: logger.error(f"[{provider_type or 'preset'}] Failed parse proxy URL for Playwright meta: {proxy_url} - Error: {e}")
            return # Playwright 处理连接

        # --- 处理标准 Scrapy HTTPS (CONNECT 隧道认证) ---
        # 仅当需要代理且是 HTTPS 请求时才添加认证头
        if needs_proxy and proxy_url and request.url.startswith('https'):
            auth_header = self.proxy_auth_headers.get(proxy_url)
            if auth_header:
                 request.headers[b'Proxy-Authorization'] = auth_header
                 logger.debug(f"[{provider_type}] Added Proxy-Authorization header for standard HTTPS: {request.url}")
            elif proxy_url: # 如果 URL 存在但没找到预计算的头
                 logger.warning(f"[{provider_type}] No pre-calculated auth header found for proxy {proxy_url}. Assuming no auth needed or check config/credentials.")

        # *** 诊断日志：检查图片请求的最终代理状态 ***
        is_image_request = 'image_urls' in request.meta or 'm.media-amazon.com/images/' in request.url
        if is_image_request:
             final_proxy = request.meta.get('proxy')
             if final_proxy:
                  logger.debug(f"Image request {request.url} proceeding WITH proxy: {final_proxy}")
             else:
                  logger.error(f"Image request {request.url} proceeding WITHOUT proxy!") # 这可以解释 Proxy None 错误

    # (process_response 和 process_exception 保持不变)
    def process_response(self, request, response, spider):
        proxy = request.meta.get('proxy')
        if response.status == 407: logger.error(f"Proxy Authentication Failed! Proxy: {proxy}...")
        elif response.status >= 500 or response.status in [403, 429]: logger.warning(f"Proxy {proxy} returned status {response.status}...")
        elif "captcha" in response.text.lower(): logger.warning(f"Proxy {proxy} likely hit a CAPTCHA...")
        return response
    def process_exception(self, request, exception, spider):
        proxy = request.meta.get('proxy')
        if isinstance(exception, TunnelError): logger.error(f"TunnelError with proxy {proxy} for {request.url}: {exception}. Check proxy connectivity and credentials for HTTPS.")
        elif "TimeoutError" in str(type(exception)): logger.error(f"Playwright TimeoutError with proxy {proxy} for {request.url}: {exception}. Amazon might be blocking or proxy is too slow.")
        else: logger.error(f"Proxy {proxy} encountered exception: {exception} for request: {request.url}")


# --- 自定义随机 User-Agent 中间件 ---
# (保持不变，包含之前的日志记录)
class CustomRandomUserAgentMiddleware:
    def __init__(self, settings):
        self.user_agents = settings.getlist('CUSTOM_USER_AGENTS')
        if not self.user_agents: logger.warning("CUSTOM_USER_AGENTS list is not defined or empty in settings.")
        else: logger.info(f"Initialized CustomRandomUserAgentMiddleware with {len(self.user_agents)} User-Agents.")
        self.fallback_ua = settings.get('FAKEUSERAGENT_FALLBACK', 'Scrapy')
    @classmethod
    def from_crawler(cls, crawler): logger.debug("CustomRandomUserAgentMiddleware: from_crawler called."); return cls(crawler.settings)
    def process_request(self, request, spider):
        logger.debug(f"CustomRandomUserAgentMiddleware: Processing request {request.url}")
        if 'User-Agent' in request.headers: logger.debug(f"CustomRandomUserAgentMiddleware: User-Agent already present: {request.headers.get(b'User-Agent', request.headers.get('User-Agent'))}"); return
        if self.user_agents: user_agent = random.choice(self.user_agents)
        else: user_agent = self.fallback_ua; logger.warning(f"CustomRandomUserAgentMiddleware: Using fallback UA: {self.fallback_ua} for request: {request.url}")
        request.headers.setdefault(b'User-Agent', user_agent.encode('utf-8'))
        logger.info(f"CustomRandomUserAgentMiddleware: Assigned User-Agent: {user_agent} for request: {request.url}")
