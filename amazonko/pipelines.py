# Define your item pipelines here
# 在此定义项目管道
# Don't forget to add your pipeline to the ITEM_PIPELINES setting
# 不要忘记将管道添加到 ITEM_PIPELINES 设置中
# See: https://docs.scrapy.org/en/latest/topics/item-pipeline.html

import csv
import os
import logging
from itemadapter import ItemAdapter # 用于方便地访问 Item 字段
from scrapy.exceptions import DropItem # 用于丢弃 Item
from scrapy.pipelines.images import ImagesPipeline # 导入图片管道基类
from scrapy import Request # 用于创建下载请求

logger = logging.getLogger(__name__)

# --- 图片下载管道 (继承并修改默认管道) ---
class CustomImagePipeline(ImagesPipeline):
    """
    处理图片下载，并将下载后的默认文件名存储到 Item 中。
    Handles image downloading and stores the default downloaded filename into the Item.
    """
    # 重写 get_media_requests 以便传递代理信息
    def get_media_requests(self, item, info):
        adapter = ItemAdapter(item)
        urls = adapter.get(self.images_urls_field, [])
        if not urls:
            logger.warning(f"Item 没有要下载的图片 URL: {adapter.get('product_url') or adapter.get('title')}")
            return

        # *** 从 Item 中获取之前保存的代理信息 ***
        proxy_to_use = adapter.get('proxy_info_for_images')
        # **************************************

        requests = []
        for url in urls:
            img_request = Request(url)
            # *** 如果获取到了代理信息，则设置到图片请求的 meta 中 ***
            if proxy_to_use:
                img_request.meta['proxy'] = proxy_to_use
                logger.debug(f"为图片 {url} 设置代理 (来自 Item): {proxy_to_use}")
            else:
                # 如果 Item 中没有代理信息（可能来自旧的或非 Playwright 请求），
                # 记录警告，并依赖中间件分配（可能导致 Proxy None）
                logger.warning(f"Item (URL: {adapter.get('product_url')}) 中缺少 proxy_info_for_images，图片请求 {url} 可能无法使用代理！")
            # ****************************************************
            requests.append(img_request)

        return requests

    def item_completed(self, results, item, info):
        """
        当一个 Item 的所有图片请求完成时 (无论成功或失败) 调用。
        Called when all image requests for an item have completed (either success or failure).
        results 是一个包含 (success, image_info_or_failure) 元组的列表。
        results is a list of tuples (success, image_info_or_failure).
        image_info_or_failure 是一个字典 (成功时) 或 Twisted Failure 对象 (失败时)。
        image_info_or_failure is a dict (on success) or a Twisted Failure object (on failure).
        """
        adapter = ItemAdapter(item)
        # 从结果中提取成功下载的图片信息中的 'path' 字段
        # Extract the 'path' field from successfully downloaded image info in results
        image_paths = [x['path'] for ok, x in results if ok and 'path' in x]

        if not image_paths:
            # 如果没有任何图片成功下载
            logger.warning(f"未能为 Item 下载任何图片: {item.get('product_url') or item.get('title')}")
            adapter['downloaded_image_name'] = None # 明确设置为空
            # 根据需求决定是否丢弃 Item
            # Decide whether to drop the Item based on requirements
            # raise DropItem(f"No images downloaded for {item.get('product_url')}")
        else:
            # 假设我们只关心第一张成功下载的图片的文件名
            # Assume we only care about the filename of the first successfully downloaded image
            # ImagesPipeline 默认使用 URL 的 SHA1 哈希作为文件名，路径类似 'full/abcdef123456.jpg'
            # ImagesPipeline uses SHA1 hash of the URL as filename by default, path is like 'full/abcdef123456.jpg'
            # 从路径中提取文件名
            # Extract the filename from the path
            adapter['downloaded_image_name'] = os.path.basename(image_paths[0])
            logger.debug(f"成功下载图片 {adapter['downloaded_image_name']} for item: {item.get('product_url')}")

        # Scrapy 的 ImagesPipeline 默认会将 results 写入 IMAGES_RESULT_FIELD 字段
        # Scrapy's ImagesPipeline will write results to the IMAGES_RESULT_FIELD by default
        # adapter[self.images_result_field] = results # 如果需要显式存储
        
        # 清理掉不再需要的代理信息 (可选)
        #if 'proxy_info_for_images' in adapter:
        #     del adapter['proxy_info_for_images']

        return item # 必须返回 Item 对象以供后续管道处理
                     # Must return the Item object for subsequent pipelines

    def file_path(self, request, response=None, info=None, *, item=None):
        """
        (可选) 重写此方法来自定义图片存储路径和文件名。
        (Optional) Override this method to customize image storage path and filename.
        默认情况下，它使用 URL 的 SHA1 哈希值。
        By default, it uses the SHA1 hash of the URL.
        需求是记录默认名称，所以我们保持默认行为。
        Requirement is to record the default name, so we keep the default behavior.
        """
        # 调用父类的默认实现
        # Call the parent class's default implementation
        return super().file_path(request, response=response, info=info, item=item)


# --- 重复数据判断管道 ---
class DuplicateItemPipeline:
    """
    根据 item 的唯一标识符 (如 product_url 或 asin) 进行去重。
    Performs deduplication based on a unique identifier of the item (e.g., product_url or asin).
    """
    def __init__(self):
        # 使用集合存储已处理过的 Item 标识符，提供快速查找
        # Use a set to store identifiers of processed items for fast lookups
        self.ids_seen = set()

    def open_spider(self, spider):
        # 爬虫启动时调用
        # Called when the spider is opened
        logger.info("DuplicateItemPipeline opened.")
        # 可选：从文件加载上次运行的 ID，实现跨次运行去重
        # Optional: Load IDs from previous runs from a file for cross-run deduplication
        # try:
        #     with open('seen_ids.txt', 'r') as f:
        #         self.ids_seen = set(line.strip() for line in f)
        #     logger.info(f"Loaded {len(self.ids_seen)} seen IDs.")
        # except FileNotFoundError:
        #     logger.info("No previous seen_ids.txt found.")

    def close_spider(self, spider):
        # 爬虫关闭时调用
        # Called when the spider is closed
        logger.info("DuplicateItemPipeline closed.")
        # 可选：将本次运行的 ID 保存到文件
        # Optional: Save IDs from the current run to a file
        # with open('seen_ids.txt', 'w') as f:
        #     for item_id in self.ids_seen:
        #         f.write(f"{item_id}\n")
        # logger.info(f"Saved {len(self.ids_seen)} seen IDs.")

    def process_item(self, item, spider):
        # 处理每个 Item
        # Process each Item
        adapter = ItemAdapter(item)
        # 优先使用 ASIN 作为唯一标识，其次使用 product_url
        # Prioritize ASIN as the unique identifier, then product_url
        item_id = adapter.get('asin') or adapter.get('product_url')

        if not item_id:
            # 如果没有唯一标识，无法去重，直接通过
            # If no unique identifier, cannot deduplicate, pass through
            logger.warning(f"Item 缺少唯一标识 (ASIN or product_url): {adapter.get('title')}")
            return item

        # 检查此 ID 是否已存在于集合中
        # Check if this ID already exists in the set
        if item_id in self.ids_seen:
            # 如果已存在，则认为是重复 Item，丢弃它
            # If it exists, consider it a duplicate Item and drop it
            raise DropItem(f"发现重复 Item: {item_id}")
        else:
            # 如果是新 Item，将其 ID 添加到集合中，并允许通过
            # If it's a new Item, add its ID to the set and let it pass through
            self.ids_seen.add(item_id)
            logger.debug(f"新 Item 添加到已见集合: {item_id}")
            return item


# --- CSV 导出管道 ---
class CsvExportPipeline:
    """
    将处理后的 Item 数据导出到 CSV 文件。
    Exports processed Item data to a CSV file.
    包含数据清洗逻辑。
    Includes data cleaning logic.
    """
    def __init__(self, settings):
        # 从设置中获取 CSV 输出文件名和要导出的字段
        # Get CSV output filename and fields to export from settings
        self.output_file = settings.get('CSV_OUTPUT_FILE', 'output.csv')
        self.fields_to_export = settings.getlist('CSV_EXPORT_FIELDS', []) # 默认为空列表
        if not self.fields_to_export:
             logger.error("CSV_EXPORT_FIELDS is not defined or empty in settings. Cannot export CSV.")
             # raise NotConfigured("CSV_EXPORT_FIELDS is required for CsvExportPipeline")
        self.file = None # 文件句柄
        self.writer = None # csv DictWriter 对象
        self.encoder = settings.get('CSV_EXPORT_ENCODING', 'utf-8') # 文件编码
        self.include_header = settings.getbool('CSV_INCLUDE_HEADER', True) # 是否包含表头
        self.first_item = True # 用于控制是否写入表头

    @classmethod
    def from_crawler(cls, crawler):
        # Scrapy 调用此方法创建管道实例，传入设置
        # Scrapy calls this method to create the pipeline instance, passing settings
        return cls(crawler.settings)

    def open_spider(self, spider):
        # 爬虫启动时调用，打开 CSV 文件
        # Called when the spider opens, opens the CSV file
        if not self.fields_to_export: return # 如果没有定义字段，则不执行任何操作

        # 确保输出目录存在
        # Ensure the output directory exists
        output_dir = os.path.dirname(self.output_file)
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except OSError as e:
                 logger.error(f"创建目录失败 {output_dir}: {e}")
                 return # 创建失败则无法继续

        try:
            # 使用 'w' 模式打开文件（覆盖），指定编码和 newline=''
            # Open the file in 'w' mode (overwrite), specify encoding and newline=''
            self.file = open(self.output_file, 'w', newline='', encoding=self.encoder)
            # 创建 DictWriter，指定字段名，extrasaction='ignore' 忽略 Item 中多余的字段
            # Create DictWriter, specify fieldnames, extrasaction='ignore' ignores extra fields in Item
            self.writer = csv.DictWriter(self.file, fieldnames=self.fields_to_export, extrasaction='ignore')
            # 如果需要写入表头且是第一次写入
            # If header is needed and it's the first write
            if self.include_header:
                self.writer.writeheader()
                self.first_item = False
            logger.info(f"CsvExportPipeline opened. Exporting to {self.output_file}")
        except IOError as e:
             logger.error(f"打开或写入 CSV 文件失败 {self.output_file}: {e}")
             self.file = None # 标记文件未成功打开

    def close_spider(self, spider):
        # 爬虫关闭时调用，关闭文件
        # Called when the spider closes, closes the file
        if self.file:
            self.file.close()
            logger.info(f"CsvExportPipeline closed. Data saved to {self.output_file}")

    def process_item(self, item, spider):
        # 处理每个 Item，进行清洗并写入 CSV
        # Process each item, perform cleaning, and write to CSV
        if not self.writer:
             logger.warning("CSV writer not available, skipping item export.")
             return item # 如果 writer 未初始化，直接返回

        adapter = ItemAdapter(item)

        # --- 数据清洗示例 ---
        # Example Data Cleaning
        # 清洗标题：去除首尾空白，合并中间多余空白
        # Clean title: strip leading/trailing whitespace, consolidate internal whitespace
        if adapter.get('title'):
            adapter['title'] = ' '.join(adapter['title'].split())

        # 确保要导出的字段都存在于 adapter 中，即使值为 None
        # Ensure all fields to export exist in the adapter, even if None
        row_data = {}
        for field in self.fields_to_export:
            row_data[field] = adapter.get(field) # 使用 get 获取，不存在则为 None

        # 提取主图 URL (如果尚未在 Item 中设置)
        # Extract main image URL (if not already set in the Item)
        if 'main_image_url' in self.fields_to_export and not row_data.get('main_image_url'):
            urls_to_download = adapter.get('image_urls_to_download')
            if urls_to_download and isinstance(urls_to_download, list) and len(urls_to_download) > 0:
                row_data['main_image_url'] = urls_to_download[0]

        # 写入 CSV 行
        # Write the row to CSV
        try:
            self.writer.writerow(row_data)
        except Exception as e:
            logger.error(f"写入 Item 到 CSV 时出错: {e} - Item: {row_data}")
            # 可以选择在这里抛出 DropItem 或记录错误后继续
            # Can choose to raise DropItem here or log the error and continue
            # raise DropItem(f"Failed to write item to CSV: {adapter.get('product_url')}")

        return item # 返回 Item 以便其他管道继续处理 (如果还有的话)
                     # Return the item for potential processing by subsequent pipelines
