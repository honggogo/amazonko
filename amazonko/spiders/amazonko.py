import scrapy
import json
import re
import logging
from urllib.parse import urljoin, urlparse, parse_qs, unquote # 导入 unquote 用于解码 URL
from scrapy.utils.response import open_in_browser # 调试时在浏览器中打开响应
from amazonko.items import AmazonkoItem # 导入定义的 Item
from scrapy.utils.project import get_project_settings # 获取项目设置
from datetime import datetime
# 导入 PageMethod 以便在 meta 中使用
from scrapy_playwright.page import PageMethod
import traceback # 用于打印更详细的 JSON 解析错误

logger = logging.getLogger(__name__)

# --- 用于清理 JSON 字符串的辅助函数 (增强版) ---
def clean_json_string(json_string):
    """尝试更健壮地清理可能包含注释或尾随逗号的 JSON 字符串"""
    if not isinstance(json_string, str): return json_string
    try:
        # 移除 JavaScript 单行注释 //...
        json_string = re.sub(r"//.*", "", json_string)
        # 移除 JavaScript 多行注释 /*...*/ (非贪婪匹配)
        json_string = re.sub(r"/\*.*?\*/", "", json_string, flags=re.DOTALL)
        # 移除行首行尾的空白符
        lines = [line.strip() for line in json_string.splitlines() if line.strip()]
        json_string = '\n'.join(lines)
        # 移除对象或数组内部及末尾的尾随逗号 (多次执行以处理嵌套)
        for _ in range(5): # 增加清理次数
            json_string = re.sub(r",\s*(\}|\])", r"\1", json_string)
        # 移除开头可能残留的非JSON字符
        json_string = re.sub(r"^[^{[]*", "", json_string)
        # 移除结尾可能残留的非JSON字符
        json_string = re.sub(r"[^}\]]*$", "", json_string)
        # 最后再清理一次尾随逗号
        json_string = re.sub(r",\s*(\}|\])", r"\1", json_string)
        return json_string.strip()
    except Exception as e:
        logger.error(f"清理 JSON 字符串时出错: {e}")
        return json_string # 清理失败则返回原始字符串

class AmazonkoSpider(scrapy.Spider):
    name = "amazonko" # 爬虫名称
    allowed_domains = ["amazon.com"] # 允许爬取的域名

    # ( __init__ 方法保持不变 )
    def __init__(self, keyword=None, max_pages=None, max_items=None, *args, **kwargs):
        super(AmazonkoSpider, self).__init__(*args, **kwargs)
        if keyword is None: raise ValueError("请使用 -a keyword='您的搜索词' 提供关键词")
        self.search_keyword = keyword
        self.start_urls = [f"https://www.amazon.com/s?k={keyword.replace(' ', '+')}"]
        settings = get_project_settings()
        self.max_pages = int(max_pages) if max_pages is not None else settings.getint('MAX_PAGES_TO_CRAWL', 0)
        self.max_items = int(max_items) if max_items is not None else settings.getint('MAX_ITEMS_TO_CRAWL', 0)
        self.crawled_pages = 0
        self.crawled_items_count = 0
        logger.info(f"启动爬虫，关键词: '{self.search_keyword}'")
        logger.info(f"最大抓取页数: {'无限制' if self.max_pages == 0 else self.max_pages}")
        logger.info(f"最大抓取商品数 (含变体): {'无限制' if self.max_items == 0 else self.max_items}")

    def start_requests(self):
        """
        生成初始请求。使用 Playwright。
        注入 JS 以尝试覆盖地理位置信息。
        使用简化的等待条件。
        """
        if not self.start_urls: logger.error("未提供关键词，无法开始请求。"); return
        settings = get_project_settings(); locale = settings.get('PLAYWRIGHT_CONTEXT_ARGS', {}).get('locale', 'en-US'); timezone_id = settings.get('PLAYWRIGHT_CONTEXT_ARGS', {}).get('timezone_id', 'America/New_York')
        # 准备注入的 JS 代码
        spoof_js = f"""
        () => {{
            try {{
                // 覆盖语言设置
                Object.defineProperty(navigator, 'language', {{ value: '{locale}', configurable: true }});
                Object.defineProperty(navigator, 'languages', {{ value: ['{locale}', 'en'], configurable: true }});
                // 尝试模拟地理位置 API (返回固定值或错误)
                if (navigator.geolocation) {{
                    navigator.geolocation.getCurrentPosition = function(success, error) {{
                        console.log('Spoofed getCurrentPosition called');
                        // success({{ coords: {{ latitude: 40.7128, longitude: -74.0060, accuracy: 100 }}, timestamp: Date.now() }}); // 模拟纽约
                        error({{ code: 1, message: "Geolocation access denied by spoof." }}); // 或者模拟拒绝
                    }};
                    navigator.geolocation.watchPosition = function(success, error) {{
                        console.log('Spoofed watchPosition called');
                        // return setInterval(() => success({{ coords: {{ latitude: 40.7128, longitude: -74.0060, accuracy: 100 }}, timestamp: Date.now() }}), 1000); // 模拟持续更新
                        error({{ code: 1, message: "Geolocation access denied by spoof." }}); // 或者模拟拒绝
                        return 0; // 返回 watchId
                    }};
                    logger.info('Geolocation API spoofed.');
                }}
                // 覆盖时区 (更可靠的方式)
                Date.prototype.getTimezoneOffset = function() {{
                    // 需要根据 timezone_id 计算正确的偏移量 (分钟)
                    // 这比较复杂，可以先返回一个固定值，例如纽约是 -240 (夏令时) 或 -300 (标准时间)
                    // 或者使用更复杂的库来计算
                    // 简单示例：返回纽约大致的偏移量
                    const offset = new Date().toLocaleString("{locale}", {{timeZone: "{timezone_id}", timeZoneName: "shortOffset"}}).split("GMT")[1];
                    if (offset) return -parseInt(offset, 10) * 60;
                    return -240; // 备用：纽约夏令时偏移
                }};
                Intl.DateTimeFormat.prototype.resolvedOptions = new Proxy(Intl.DateTimeFormat.prototype.resolvedOptions, {{
                    apply(target, self, args) {{
                        const options = Reflect.apply(target, self, args);
                        options.timeZone = '{timezone_id}';
                        options.locale = '{locale}';
                        return options;
                    }}
                 }});
                 logger.info('Timezone and Locale spoofed.');
            }} catch (e) {{ console.error('Error during JS spoofing:', e); }}
        }}
        """

        for url in self.start_urls:
            yield scrapy.Request(
                url,
                callback=self.parse_search_results,
                meta={
                    'playwright': True, # 启用 Playwright
                    'playwright_include_page': True, # 需要访问 Playwright Page 对象
                    'playwright_context_kwargs': { # 继续传递上下文参数
                        'locale': locale,
                        'timezone_id': timezone_id,
                        'geolocation': None, # 禁用默认地理位置
                        'permissions': [], # 清空权限
                        'viewport': {"width": 1920, "height": 1080}, # 保持视口设置
                    },
                    'playwright_page_goto_options': {
                        'wait_until': 'domcontentloaded', # 等待 DOM 加载即可
                    },
                    'playwright_page_methods': [
                        # *** 在页面加载前执行 JS 注入 ***
                        PageMethod('evaluate', spoof_js),
                        # *******************************
                        # 等待条件：等待第一个搜索结果项容器可见
                        PageMethod('wait_for_selector', 'div.s-result-item[data-asin]', state='visible', timeout=60000),
                    ],
                    'current_page': 1
                },
                errback=self.errback_handle, # 指定错误处理函数
            )

    async def parse_search_results(self, response):
        """
        解析搜索结果页面。
        使用上次成功的选择器。
        修正了详情页请求的 meta 和等待条件。
        """
        page_number = response.meta.get('current_page', 1); self.crawled_pages += 1
        logger.info(f"正在解析搜索结果页面: {page_number} - URL: {response.url}")
        page = response.meta.get('playwright_page')

        # 检查是否是错误页面（例如包含 "page not found" 或 "狗页面" 的标题）
        page_title = await page.title() if page else response.css('title::text').get('')
        if "page not found" in page_title.lower() or "sorry" in page_title.lower() or "robot check" in page_title.lower():
            logger.error(f"检测到错误/阻止页面 (标题: {page_title})，URL: {response.url}。跳过解析。")
            if page and not page.is_closed(): await page.close()
            return # 不再处理此错误页面

        # *** 使用上次成功的选择器 ***
        PRODUCT_LINK_SELECTOR = 'a.a-link-normal.s-no-outline[href*="/dp/"]::attr(href)'
        # **************************

        product_links_raw = response.css(PRODUCT_LINK_SELECTOR).getall()
        logger.info(f"使用选择器 '{PRODUCT_LINK_SELECTOR}' 在页面 {page_number} 找到 {len(product_links_raw)} 个链接。")

        # (链接验证和去重逻辑保持不变)
        valid_product_links = []
        seen_asins = set()
        for link in product_links_raw:
            if '/sspa/click' in link:
                try:
                    parsed_qs_data = parse_qs(urlparse(link).query)
                    if 'url' in parsed_qs_data: link = urljoin(response.url, unquote(parsed_qs_data['url'][0]).split('?')[0])
                    else: continue
                except Exception as e: logger.warning(f"解析 SSPA 链接时出错: {link} - Error: {e}"); continue
            else: link = urljoin(response.url, link.split('?')[0])
            asin_match = re.search(r'/(dp|gp/product)/([A-Z0-9]{10})', link)
            if asin_match:
                asin = asin_match.group(2)
                if asin not in seen_asins: seen_asins.add(asin); valid_product_links.append(link)
            else: logger.debug(f"链接不含 ASIN，跳过: {link}")
        logger.info(f"在页面 {page_number} 找到 {len(valid_product_links)} 个有效且唯一的商品链接")
        if not valid_product_links:
             logger.warning(f"在页面 {page_number} 未找到有效的商品链接。请检查主要选择器 '{PRODUCT_LINK_SELECTOR}' 和页面内容。")
             if page: # 保存调试文件
                 try:
                     html_content = await page.content()
                     with open(f"page_{page_number}_nolinks_source.html", "w", encoding="utf-8") as f: f.write(html_content)
                     await page.screenshot(path=f"page_{page_number}_nolinks_screenshot.png", full_page=True)
                     logger.info(f"已保存页面 {page_number} (无有效链接) 的源码和截图。")
                 except Exception as e: logger.error(f"保存调试文件失败: {e}")

        # 处理商品链接
        for product_url in valid_product_links:
            if self.max_items > 0 and self.crawled_items_count >= self.max_items: logger.info(...); return
            asin_match = re.search(r'/(dp|gp/product)/(\w{10})', product_url); asin = asin_match.group(2) if asin_match else None
            if not asin: logger.error(...); continue

            # *** 获取当前请求使用的代理信息，传递给详情页请求 ***
            current_proxy = response.request.meta.get('proxy')
            # *************************************************

            yield scrapy.Request(
                product_url, callback=self.parse_product_detail,
                meta={
                    'playwright': True, 'playwright_include_page': True,
                    'playwright_page_goto_options': {'wait_until': 'domcontentloaded'},
                    # *** 修改详情页等待条件：等待更通用的容器 ***
                    'playwright_page_methods': [
                        PageMethod('wait_for_selector', '#dp-container', state='visible', timeout=60000)
                    ],
                    # *****************************************
                    'asin': asin, 'search_keyword': self.search_keyword,
                    'handle_httpstatus_list': [404, 503],
                    'proxy_info_for_images': current_proxy # <-- 将代理信息传递下去
                }, priority=10, errback=self.errback_handle,
            )

        # (翻页逻辑保持不变)
        if self.max_pages > 0 and self.crawled_pages >= self.max_pages: logger.info(f"已达到最大抓取页数 ({self.max_pages})，停止翻页。"); return
        next_page_selector = 'a.s-pagination-item.s-pagination-next'
        next_page_relative_url = response.css(next_page_selector + '::attr(href)').get()
        if next_page_relative_url:
            next_page_url = urljoin(response.url, next_page_relative_url)
            logger.info(f"找到下一页链接: {next_page_url}")
            yield scrapy.Request(
                next_page_url, callback=self.parse_search_results,
                meta={
                    'playwright': True, 'playwright_include_page': True,
                    'playwright_page_goto_options': {'wait_until': 'domcontentloaded'},
                    'playwright_page_methods': [
                        PageMethod('wait_for_selector', 'div.s-result-item[data-asin]', state='visible', timeout=60000)
                    ],
                    'current_page': page_number + 1,
                }, errback=self.errback_handle,
            )
        else: logger.info("未找到下一页链接...")
        if page and not page.is_closed(): await page.close()

    async def parse_product_detail(self, response):
        """
        解析商品详情页面。
        增强了主图提取和 JSON 解析。
        从 meta 获取代理信息以传递给 Item。
        """
        page = response.meta.get('playwright_page')
        asin = response.meta.get('asin')
        search_keyword = response.meta.get('search_keyword')
        product_url = response.url
        # *** 获取传递过来的代理信息 ***
        proxy_info = response.request.meta.get('proxy_info_for_images')
        # ***************************
        if not asin: logger.error(f"详情页请求未能接收到 ASIN: {response.url}"); return

        try:
            if response.status in [404, 503]: logger.warning(...); return

            # 检查是否是错误页面
            page_title = await page.title() if page else response.css('title::text').get('')
            if "page not found" in page_title.lower() or "sorry" in page_title.lower() or "robot check" in page_title.lower():
                logger.error(f"检测到详情页错误/阻止页面 (标题: {page_title})，URL: {response.url}。跳过解析。")
                return

            logger.info(f"正在解析商品详情页: {product_url} (ASIN: {asin})")

            # (提取 title 和 main_image_url 逻辑不变)
            title = response.css('#productTitle::text').get('').strip() or response.css('h1#title span#productTitle::text').get('').strip() or "N/A"
            
            # *** 增强主图 URL 提取逻辑 ***
            main_image_url = None
            large_image_url_from_json = None # 存储从 JSON 找到的最大图
            try:
                # 1. 优先解析 data-a-dynamic-image JSON
                dynamic_image_data = response.css('#imgTagWrapperId img::attr(data-a-dynamic-image)').get() \
                                     or response.css('#landingImage::attr(data-a-dynamic-image)').get() # 备用选择器
                if dynamic_image_data:
                    try:
                        image_dict = json.loads(dynamic_image_data)
                        valid_urls = {url: size for url, size in image_dict.items() if isinstance(size, list) and len(size) == 2 and url.startswith('http')}
                        if valid_urls:
                             # 找到分辨率最高的 URL
                             large_image_url_from_json = max(valid_urls, key=lambda k: valid_urls[k][0] * valid_urls[k][1])
                             logger.debug(f"通过 data-a-dynamic-image 找到主图: {large_image_url_from_json[:60]}...")
                    except (json.JSONDecodeError, ValueError, TypeError) as e:
                        logger.warning(f"解析 data-a-dynamic-image JSON 失败 (ASIN: {asin}): {e}")

                # 2. 如果 JSON 成功解析出 URL，则使用它
                if large_image_url_from_json:
                     main_image_url = large_image_url_from_json
                else:
                    # 3. 否则，尝试 #landingImage 的 src
                    main_image_url = response.css('#landingImage::attr(src)').get()
                    if main_image_url: logger.debug(f"通过 #landingImage src 找到主图: {main_image_url[:60]}...")
                    else:
                        # 4. 最后尝试 #imgTagWrapperId img 的 src
                        main_image_url = response.css('#imgTagWrapperId img::attr(src)').get()
                        if main_image_url: logger.debug(f"通过 #imgTagWrapperId img src 找到主图: {main_image_url[:60]}...")

                # 尝试去除 URL 中的尺寸参数 (如果存在且看起来是标准格式)
                if main_image_url and '._' in main_image_url.split('/')[-1]: # 检查最后一部分是否包含 '._'
                     try:
                         base_url, ext_part = main_image_url.rsplit('._', 1)
                         ext = os.path.splitext(ext_part)[1] # 获取 .jpg, .png 等
                         if ext.lower() in ['.jpg', '.png', '.gif', '.jpeg', '.webp']:
                              cleaned_url = base_url + ext
                              logger.debug(f"尝试清理图片 URL: {main_image_url} -> {cleaned_url}")
                              main_image_url = cleaned_url
                     except ValueError: # 如果 rsplit 失败
                          logger.debug(f"无法按 '._' 分割 URL 进行清理: {main_image_url}")

            except Exception as e:
                 logger.error(f"提取主图 URL 时发生意外错误 (ASIN: {asin}): {e}")
                 
            if not main_image_url: logger.warning(f"最终未能提取主图 URL (ASIN: {asin})")
            
            # --- 创建主商品的 Item ---
            item = AmazonkoItem()
            item['search_keyword'] = search_keyword; item['product_url'] = product_url; item['asin'] = asin; item['title'] = title; item['image_urls_to_download'] = [main_image_url] if main_image_url else []; item['is_variation'] = False; item['crawled_at'] = datetime.now().isoformat()
            # *** 将代理信息存入 Item，以便图片管道使用 ***
            item['proxy_info_for_images'] = proxy_info
            # ******************************************

            if self.max_items > 0 and self.crawled_items_count >= self.max_items: return
            self.crawled_items_count += 1
            logger.debug(f"Yielding 主商品: ASIN={asin}...")
            yield item
            
            
            # --- 提取颜色变体信息 ---
            variation_data_script = response.xpath("//script[contains(text(), 'dimensionValuesDisplayData')]/text()").get()
            variation_asin_map = {}
            variation_image_map = {}

            if variation_data_script:
                logger.debug(f"尝试从 script 标签解析变体 JSON (ASIN: {asin})")
                try:
                    # *** 增强 JSON 清理和解析 ***
                    json_match = None
                    patterns = [r'"dimensionValuesDisplayData"\s*:\s*({.*?}),\s*"variationValues"', r'jQuery\.parseJSON\(\'(.*?)\'\);', r'var dataToReturn = ({.*?});']
                    for pattern in patterns:
                        json_match = re.search(pattern, variation_data_script, re.DOTALL | re.IGNORECASE)
                        if json_match: break

                    if json_match:
                        variation_json_str = json_match.group(1)
                        # 清理字符串
                        cleaned_json_str = clean_json_string(variation_json_str)
                        try:
                            variation_data = json.loads(cleaned_json_str)
                            # (后续解析 color_data 和 color_images 逻辑不变)
                            if 'dimensionValuesDisplayData' in variation_data:
                                for var_asin, details in variation_data.get('dimensionValuesDisplayData', {}).items():
                                    if var_asin != asin and isinstance(details, list) and details: variation_asin_map[var_asin] = details[0]
                            if 'colorImages' in variation_data:
                                 for var_asin, images in variation_data.get('colorImages', {}).items():
                                     if var_asin != asin and isinstance(images, list) and images:
                                         var_image_url = None
                                         for img_data in images:
                                             if isinstance(img_data, dict):
                                                 if img_data.get('variant') == 'MAIN':
                                                     if img_data.get('hiRes'): var_image_url = img_data['hiRes']; break
                                                     elif img_data.get('large'): var_image_url = img_data['large']
                                         if not var_image_url and isinstance(images[0], dict): var_image_url = images[0].get('large')
                                         if var_image_url: variation_image_map[var_asin] = var_image_url; logger.debug(f"找到变体图片: ASIN={var_asin}...")
                        except json.JSONDecodeError as json_err:
                             logger.error(f"清理后 JSON 解析失败 (ASIN: {asin}): {json_err}")
                             logger.debug(f"清理后的 JSON 字符串片段: {cleaned_json_str[:500]}")
                    else:
                         logger.warning(f"无法从脚本中提取变体 JSON 结构 (ASIN: {asin})")
                except Exception as e:
                     logger.error(f"处理变体脚本时发生意外错误 (ASIN: {asin}): {e}\n{traceback.format_exc()}")

            # (HTML swatch 提取逻辑不变)
            if not variation_asin_map:
                color_swatches = response.css('ul[aria-labelledby="color_name-label"] li[data-asin]') or response.css('#variation_color_name ul li')
                # ... (swatch 解析逻辑) ...

            # (创建变体 Item 逻辑不变)
            logger.info(f"共找到 {len(variation_asin_map)} 个颜色变体 (ASIN: {asin})。")
            for var_asin, color in variation_asin_map.items():
                # ... (检查限制, 获取图片, 创建 Item, yield Item) ...
                if self.max_items > 0 and self.crawled_items_count >= self.max_items: return
                var_image_url = variation_image_map.get(var_asin, main_image_url)
                if not var_image_url: logger.error(...); continue
                variation_item = AmazonkoItem()
                # ... (填充 variation_item) ...
                variation_item['search_keyword'] = search_keyword; variation_item['product_url'] = f"{product_url.split('/dp/')[0]}/dp/{var_asin}"; variation_item['asin'] = var_asin; variation_item['title'] = f"{title} ({color})"; variation_item['image_urls_to_download'] = [var_image_url]; variation_item['is_variation'] = True; variation_item['variation_type'] = 'Color'; variation_item['variation_value'] = color; variation_item['crawled_at'] = datetime.now().isoformat()
                # *** 将代理信息也存入变体 Item *** 11:11新增
                variation_item['proxy_info_for_images'] = proxy_info
                # **********************************
                self.crawled_items_count += 1
                yield variation_item

        finally:
            # 确保 Playwright 页面关闭
             if page and not page.is_closed():
                await page.close()

    async def errback_handle(self, failure):
        # (内容同上一版本，包含截图)
        logger.error(f"请求失败: {failure.request.url} - 类型: {failure.type} - 值: {failure.value}")
        page = failure.request.meta.get('playwright_page')
        if page and not page.is_closed():
            logger.debug(f"尝试关闭失败请求的页面: {failure.request.url}")
            try:
                 timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                 screenshot_path = f"error_screenshot_{timestamp}.png"
                 await page.screenshot(path=screenshot_path, full_page=True)
                 logger.info(f"已保存错误截图: {screenshot_path} (针对 URL: {failure.request.url})")
            except Exception as ss_err: logger.error(f"保存错误截图失败: {ss_err}")
            try: await page.close(); logger.debug(f"因错误关闭 Playwright 页面: {failure.request.url}")
            except Exception as e: logger.error(f"关闭失败的 Playwright 页面时出错: {e}")

