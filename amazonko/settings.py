# Scrapy settings for amazonko project
import random
import re
from shutil import which

# ... (BOT_NAME, SPIDER_MODULES, etc. 保持不变) ...
BOT_NAME = "amazonko"
SPIDER_MODULES = ["amazonko.spiders"]
NEWSPIDER_MODULE = "amazonko.spiders"

# ... (基本设置, CUSTOM_USER_AGENTS, 中间件, 管道等保持不变) ...
ROBOTSTXT_OBEY = False
CONCURRENT_REQUESTS = 4
DOWNLOAD_DELAY = 1.5
CONCURRENT_REQUESTS_PER_DOMAIN = 4
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9", # 简化语言设置，只保留 en-US 和 en
    "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1", "Upgrade-Insecure-Requests": "1",
}
# --- 自定义 User-Agent 列表 ---
CUSTOM_USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/110.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Mobile/15E148 Safari/604.1'
]
FAKEUSERAGENT_FALLBACK = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36'
DOWNLOADER_MIDDLEWARES = {
    'scrapy.downloadermiddlewares.retry.RetryMiddleware': 90,
    'scrapy.downloadermiddlewares.cookies.CookiesMiddleware': None,
    'scrapy.downloadermiddlewares.useragent.UserAgentMiddleware': None,
    'scrapy_fake_useragent.middleware.RandomUserAgentMiddleware': None,
    'amazonko.middlewares.CustomRandomUserAgentMiddleware': 400,
    'amazonko.middlewares.CustomHttpProxyMiddleware': 543,
    'scrapy.downloadermiddlewares.httpproxy.HttpProxyMiddleware': None,
    'scrapy.downloadermiddlewares.httpcompression.HttpCompressionMiddleware': 810,
    'scrapy.downloadermiddlewares.redirect.RedirectMiddleware': 900,
    'scrapy.downloadermiddlewares.httpcache.HttpCacheMiddleware': 950,
}
ITEM_PIPELINES = {
   "amazonko.pipelines.DuplicateItemPipeline": 100,
   "amazonko.pipelines.CustomImagePipeline": 200,
   "amazonko.pipelines.CsvExportPipeline": 300,
}
IMAGES_STORE = 'images'
IMAGES_URLS_FIELD = 'image_urls_to_download'
IMAGES_RESULT_FIELD = 'image_download_results'
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
AUTOTHROTTLE_DEBUG = True
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 0
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_IGNORE_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429, 403, 407]
REQUEST_FINGERPRINTER_IMPLEMENTATION = '2.7'
# JOBDIR = 'crawls/amazonko-runX'

# --- Playwright 设置 ---
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
#PLAYWRIGHT_BROWSER_TYPE = "firefox" # 可以尝试 'firefox' 或 'webkit'
PLAYWRIGHT_BROWSER_TYPE = "chromium" # 可以尝试 'firefox' 或 'webkit'

# --- 资源阻止 (保持禁用) ---
PLAYWRIGHT_ABORT_REQUEST = None

# Playwright 浏览器启动参数
PLAYWRIGHT_LAUNCH_OPTIONS = {
    "headless": False, # *** 保持 False 以便观察！ ***
    "timeout": 180 * 1000,
    "args": [
        "--disable-blink-features=AutomationControlled",
        "--lang=en-US",
        # *** 新增：尝试禁用 WebRTC 相关功能来防止 IP 泄露 ***
        "--disable-features=WebRtcHideLocalIpsWithMdns",
        "--denylist-features=WebRtcIPHandling", # Chromium 较新版本可能使用这个
        # **************************************************
        # "--window-size=1920,1080",
        # "--no-sandbox",
        # "--disable-dev-shm-usage"
    ],
}
# Playwright 页面导航超时
PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT = 180 * 1000
# Playwright 上下文参数 (继续尝试模拟地理位置)
PLAYWRIGHT_CONTEXT_ARGS = {
    "locale": "en-US",
    "timezone_id": "America/New_York", # 假设代理在美国
    "geolocation": None,
    "permissions": [], # 清空权限
    "viewport": {"width": 1920, "height": 1080},
    "java_script_enabled": True,
}

# --- 通用代理配置 ---
# (保持不变，确保凭据和列表正确, 并启用你想用的代理)
PROXY_CONFIG = [
    {
        'provider_type': 'oxylabs_isp',
        'username': 'amazon_CAxH4',
        'password': 'hong123123_CAxH4',
        'endpoints': [
            "http://{username}:{password}@isp.oxylabs.io:8001",
            "http://{username}:{password}@isp.oxylabs.io:8002",
            "http://{username}:{password}@isp.oxylabs.io:8003",
            "http://{username}:{password}@isp.oxylabs.io:8004",
            "http://{username}:{password}@isp.oxylabs.io:8005",
            # ... 其他 Oxylabs 端点 ...
        ],
        'headers': {},
        'enabled': True # 启用 Oxylabs
    },
    {
        'provider_type': '16yun',
        'username': 'YOUR_16YUN_USERNAME',
        'password': 'YOUR_16YUN_PASSWORD',
        'host': 't.16yun.cn', 'port': '31111',
        'proxy_url_format': "http://{username}:{password}@{host}:{port}",
        'endpoints': ["t.16yun.cn:31111"],
        'headers': { 'Connection': 'Close' },
        'enabled': False # 设为 True 来启用 16yun
    },
]
# (代理配置检查逻辑保持不变)
if not any(p.get('enabled') for p in PROXY_CONFIG): print("...警告：没有启用的代理配置...")

# --- 其他设置 ---
# (日志 / 重试 / CSV 设置保持不变)
#LOG_LEVEL = 'INFO'
LOG_LEVEL = 'DEBUG'
LOG_FILE = 'amazonko.log' # 启用日志文件记录 DEBUG 信息
RETRY_ENABLED = True
RETRY_TIMES = 5
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429, 403, 407]
CSV_OUTPUT_FILE = 'amazon_products.csv'
CSV_EXPORT_FIELDS = [
    'title', 'main_image_url', 'downloaded_image_name', 'product_url', 'asin',
    'search_keyword', 'is_variation', 'variation_type', 'variation_value', 'crawled_at'
]
CSV_EXPORT_ENCODING = 'utf-8'
CSV_INCLUDE_HEADER = True
